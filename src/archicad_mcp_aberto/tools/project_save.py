"""Save the open project as a new PLN through the ArchicadMcpAberto add-on (addon/).

The official JSON API and Tapir 1.7 have no save command, so SaveProjectAsPLN calls
ACAPI_ProjectOperation_Save in our add-on. It saves what is open in Archicad, unsaved
changes included; it is not a copy of the file on disk.

save_project_as saves to an explicit absolute .pln path. save_next_project_revision is
the office routine (Vitor, 27/10/2026): "WG Formosa_R04.pln" is saved as
"WG Formosa_R05.pln" in the same folder, and once that save is confirmed the R04 file
moves to "00 - Anteriores". Both refuse an existing destination, Teamwork projects and
in-place overwrites. Saving and moving files are not Archicad Undo steps.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Annotated

from pydantic import Field

from archicad_mcp_aberto.connection import AddOnError, ArchicadClient, ArchicadError, resolve_port
from archicad_mcp_aberto.tools import grids, solids, write

ARCHIVE_FOLDER = "00 - Anteriores"
# "WG Formosa_R04", "Casa REV2", "Loja-r10": a separator, R or REV, then the number.
REVISION = re.compile(r"^(?P<base>.+?)(?P<tag>[ _-](?:REV|R))(?P<number>\d+)$", re.IGNORECASE)
FolderName = Annotated[str, Field(min_length=1, max_length=120, pattern=r"^[^\\/:*?\"<>|]+$")]


class SaveRequest(write.InputModel):
    destination_path: Annotated[str, Field(min_length=1, max_length=1000)] | None = None
    archive_folder: FolderName | None = None


def _pln(value: str, label: str) -> Path:
    if "\x00" in value or "\n" in value or "\r" in value:
        raise ValueError(f"{label}: unsafe characters in the path.")
    path = Path(value)
    if not path.is_absolute() or path.suffix.casefold() != ".pln" or ".." in path.parts:
        raise ValueError(f"{label}: an absolute path to a .pln file is required.")
    return path


def _same(a: Path | str, b: Path | str) -> bool:
    return os.path.normcase(os.path.normpath(str(a))) == os.path.normcase(os.path.normpath(str(b)))


def _stamp(path: Path) -> dict | None:
    """Size and modification time, to notice a file that changed after the preview."""
    if not path.exists():
        return None
    if not path.is_file():
        raise ValueError(f"Not a file: {path}")
    info = path.stat()
    return {"size": info.st_size, "mtime_ns": info.st_mtime_ns}


def next_revision(source: Path, archive: Path) -> Path:
    """The next free revision name, looking in the project folder and its archive."""
    match = REVISION.fullmatch(source.stem)
    base, tag, digits = match.group("base", "tag", "number") if match else (source.stem, "_R", "")
    highest = int(digits) if digits else 0
    pattern = re.compile(re.escape(base + tag) + r"(\d+)\.pln", re.IGNORECASE)
    for folder in (source.parent, archive):
        if folder.is_dir():
            for child in folder.iterdir():
                found = pattern.fullmatch(child.name)
                if found:
                    highest = max(highest, int(found[1]))
    return source.with_name(f"{base}{tag}{highest + 1:0{max(2, len(digits))}d}.pln")


async def _context(client, port) -> dict:
    raw = await grids._addon(client, port, "GetProjectSaveContext")
    if not isinstance(raw, dict) or not {"untitled", "teamwork"} <= raw.keys():
        raise ValueError("Unexpected GetProjectSaveContext response; update the add-on.")
    return {k: raw.get(k) for k in ("untitled", "teamwork", "projectPath", "projectName")}


async def _plan(client, requests, port, operation):
    (request,) = requests
    port = await resolve_port(client, port)
    project = await _context(client, port)
    if project["teamwork"]:
        raise ValueError("Teamwork projects are not saved by this tool; use Send & Receive.")
    saved = not project["untitled"] and isinstance(project["projectPath"], str)
    source = _pln(project["projectPath"], "Open project") if saved else None
    item: dict = {"index": 0, "status": "ready", "source_path": str(source) if source else None}
    if request.archive_folder is None:
        destination = _pln(request.destination_path or "", "destination_path")
    else:
        if source is None:
            raise ValueError("The project was never saved; use save_project_as first.")
        if not source.is_file():
            raise ValueError(f"The open project's file is missing on disk: {source}")
        archive = source.parent / request.archive_folder
        if archive.exists() and not archive.is_dir():
            raise ValueError(f"{archive} exists and is not a folder.")
        destination = next_revision(source, archive)
        moved = archive / source.name
        if moved.exists():
            raise ValueError(f"{moved} already exists; the previous revision is not moved.")
        item.update(archive_path=str(moved), previous_file=_stamp(source))
    if source is not None and _same(source, destination):
        raise ValueError("Save As needs a new file name; overwriting the open file is refused.")
    if not destination.parent.is_dir():
        raise ValueError(f"The folder {destination.parent} does not exist.")
    if destination.exists():
        raise ValueError(f"{destination} already exists; it is never overwritten.")
    item["destination_path"] = str(destination)
    return {
        "operation": operation,
        "target": {"port": port, "project": project},
        "items": [item],
    }


def _move(source: Path, destination: Path) -> None:
    if os.name == "nt":
        os.rename(source, destination)  # refuses an existing destination on Windows
    else:
        os.link(source, destination)  # refuses an existing destination; then drop the old
        source.unlink()


async def _dispatch(client, receipt):
    (item,) = receipt["items"]
    port = receipt["target"]["port"]
    destination = Path(item["destination_path"])
    receipt["undo_scope"] = "Saving and moving files are not Archicad Undo steps."
    if destination.exists():
        item.update(status="failed", error=f"{destination} appeared after the preview.")
        return
    try:
        await grids._addon(
            client,
            port,
            "SaveProjectAsPLN",
            {
                "destinationPath": str(destination),
                "expectedProjectPath": item["source_path"] or "",
            },
            receipt["write_timeout_seconds"],
        )
    except AddOnError as exc:
        # The add-on answered with an error (or is not loaded): nothing was saved.
        item.update(status="failed", error=exc.detail or str(exc))
        return
    except ArchicadError as exc:
        return solids._unknown(receipt, f"SaveProjectAsPLN: {exc}")
    item["status"] = "unverified"
    try:
        after = await _context(client, port)
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    item["after"] = after
    saved = _stamp(destination)
    if after["untitled"] or not _same(after.get("projectPath") or "", destination):
        item.update(status="verification_failed", error="Archicad does not show the new file.")
        return
    if not saved or saved["size"] <= 0:
        item.update(status="verification_failed", error="The new PLN is missing or empty.")
        return
    item.update(save_verified=True, saved_file=saved)
    if "archive_path" in item:
        source, moved = Path(item["source_path"]), Path(item["archive_path"])
        try:
            if _stamp(source) != item["previous_file"]:
                raise ValueError("the previous file changed after the preview")
            moved.parent.mkdir(exist_ok=True)
            _move(source, moved)
        except (OSError, ValueError) as exc:
            item.update(
                status="verification_failed",
                archive_verified=False,
                error=f"Saved as {destination.name}, but {source.name} was not moved: {exc}. "
                "Move it by hand.",
            )
            return
        item["archive_verified"] = not source.exists() and _stamp(moved) == item["previous_file"]
        if not item["archive_verified"]:
            item.update(status="verification_failed", error="Inspect the archive folder.")
            return
    item["status"] = "verified"


async def _save(client, request, port, dry_run, confirmation_token, operation):
    return await write._write(
        client,
        [request],
        port,
        dry_run,
        confirmation_token,
        operation,
        planner_override=_plan,
        dispatcher_override=_dispatch,
        completion_note="Saving and file moves cannot be undone in Archicad. Check "
        "save_verified and archive_verified.",
    )


async def save_project_as(
    client: ArchicadClient,
    destination_path: str,
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply saving the open project, unsaved changes included, as a new PLN at an
    absolute path. Never overwrites a file."""
    request = SaveRequest(destination_path=destination_path)
    return await _save(client, request, port, dry_run, confirmation_token, "save_project_as")


async def save_next_project_revision(
    client: ArchicadClient,
    port: int | None = None,
    archive_folder: str = ARCHIVE_FOLDER,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply saving the open project as its next revision (_R04 -> _R05) in the
    same folder, then moving the previous PLN into archive_folder."""
    request = SaveRequest(archive_folder=archive_folder)
    return await _save(
        client, request, port, dry_run, confirmation_token, "save_next_project_revision"
    )
