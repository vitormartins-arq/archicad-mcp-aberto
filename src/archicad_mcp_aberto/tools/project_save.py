"""Native Save As and next-revision archival, including unsaved model changes."""

from __future__ import annotations

import os
import re
import stat
from pathlib import Path

from archicad_mcp_aberto.connection import ArchicadError, resolve_port
from archicad_mcp_aberto.tools import grids, write

REVISION = re.compile(r"^(.*)([ _-](?:REV|R))(\d+)([ _-].*)?$", re.IGNORECASE)


class SaveRequest(write.InputModel):
    destination_path: str | None = None
    archive_previous: bool = False


def _path(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or path.suffix.casefold() != ".pln":
        raise ValueError("An absolute .pln path is required.")
    if any(c in value for c in ("\x00", "\n", "\r")) or ".." in path.parts:
        raise ValueError("Unsafe destination path.")
    if any(":" in part or part.endswith((" ", ".")) for part in path.parts[1:]):
        raise ValueError("Alternate streams and ambiguous path components are refused.")
    for part in (path, *path.parents):
        if part.is_symlink() or (
            part.exists()
            and getattr(part.lstat(), "st_reparse_tag", 0)
            == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)
        ):
            raise ValueError("Symbolic links and junctions are not supported.")
    return path


def _fingerprint(path: Path) -> dict | None:
    if not path.exists():
        return None
    value = path.stat()
    if not stat.S_ISREG(value.st_mode):
        raise ValueError(f"Not a regular file: {path}")
    return {
        "size": value.st_size,
        "mtime_ns": value.st_mtime_ns,
        "device": value.st_dev,
        "inode": value.st_ino,
    }


def _revision_path(source: Path, archive: Path) -> Path:
    match = REVISION.fullmatch(source.stem)
    stem, label, digits, suffix = match.groups() if match else (source.stem, "_R", "00", "")
    suffix = suffix or ""
    highest = int(digits)
    pattern = re.compile(
        re.escape(stem + label) + r"(\d+)" + re.escape(suffix) + r"\.pln", re.IGNORECASE
    )
    for folder in (source.parent, archive):
        if folder.exists():
            for child in folder.iterdir():
                found = pattern.fullmatch(child.name)
                if found:
                    highest = max(highest, int(found[1]))
    return source.with_name(f"{stem}{label}{highest + 1:0{max(2, len(digits))}d}{suffix}.pln")


def _archive_path(source: Path, folder: Path) -> Path:
    destination = folder / source.name
    counter = 0
    while destination.exists():
        counter += 1
        if counter > 10000:
            raise ValueError("Too many archive collisions.")
        destination = folder / f"{source.stem}__archive_{counter:03d}{source.suffix}"
    return destination


async def _context(client, port):
    raw = await grids._addon(client, port, "GetProjectSaveContext")
    needed = {
        "sessionId",
        "projectEpoch",
        "projectPath",
        "modificationStamp",
        "untitled",
        "teamwork",
    }
    if not isinstance(raw, dict) or not needed <= raw.keys():
        raise ValueError("Incomplete native save context; update the companion add-on.")
    if raw["teamwork"] is not False:
        raise ValueError("Teamwork projects are not supported by Save As PLN.")
    if (
        any(not isinstance(raw[k], str) for k in needed - {"untitled", "teamwork"})
        or not raw["sessionId"]
        or not raw["projectEpoch"]
        or not raw["modificationStamp"].isdigit()
        or type(raw["untitled"]) is not bool
    ):
        raise ValueError("Invalid native save identity.")
    return {key: raw[key] for key in sorted(needed)}


async def _plan(client, requests, port, operation):
    (request,) = requests
    port = await resolve_port(client, port)
    context = await _context(client, port)
    source = _path(context["projectPath"]) if context["projectPath"] else None
    if request.archive_previous and (source is None or context["untitled"] is not False):
        raise ValueError("Save the untitled project to an explicit PLN path first.")
    folder = source.parent / "Anteriores" if source else None
    if request.archive_previous and folder and folder.exists() and not folder.is_dir():
        raise ValueError("Anteriores already exists and is not a folder.")
    destination = (
        _path(request.destination_path)
        if request.destination_path
        else _revision_path(source, folder)
        if source
        else None
    )
    if destination is None:
        raise ValueError("An explicit destination_path is required for an untitled project.")
    destination = _path(str(destination))
    if not destination.parent.is_dir() or destination.exists():
        raise ValueError("Destination parent must exist and the PLN must not already exist.")
    if source and os.path.normcase(str(source.resolve())) == os.path.normcase(
        str(destination.resolve())
    ):
        raise ValueError("In-place overwrite is refused.")
    previous = _fingerprint(source) if source and request.archive_previous else None
    if request.archive_previous and (previous is None or previous["size"] == 0):
        raise ValueError("Previous revision is missing or empty; archival refused.")
    archived = _archive_path(source, folder) if request.archive_previous else None
    if archived:
        _path(str(archived))
    return {
        "operation": operation,
        "target": {"port": port, "project": context},
        "items": [
            {
                "index": 0,
                "status": "ready",
                "source_path": str(source) if source else None,
                "destination_path": str(destination),
                "archive_path": str(archived) if archived else None,
                "previous_file": previous,
            }
        ],
        "warnings": [
            "Saves the current open project including unsaved changes via native API.",
            "No Undo for saving or archival. Existing destinations are refused.",
            "Previous revision moves only after native path and nonempty PLN verification.",
        ],
    }


def _move_no_replace(source: Path, destination: Path):
    if os.name == "nt":
        os.rename(source, destination)  # Windows refuses an existing destination.
    else:
        os.link(source, destination, follow_symlinks=False)
        source.unlink()  # Complete the user-requested move, only after the exclusive link.


async def _dispatch(client, receipt):
    item = receipt["items"][0]
    port = receipt["target"]["port"]
    try:
        destination = _path(item["destination_path"])
        if destination.exists():
            raise ValueError("Destination appeared after preview.")
        await grids._addon(
            client,
            port,
            "SaveProjectAsPLN",
            {"destinationPath": str(destination), **receipt["target"]["project"]},
            receipt["write_timeout_seconds"],
        )
    except (ValueError, OSError) as exc:
        item.update(status="failed", error=str(exc))
        return
    except ArchicadError as exc:
        item.update(status="unknown", error=str(exc))
        receipt["warning"] = (
            "Save outcome unknown. Inspect this receipt, destination and "
            "native project context before any new write; never retry this token."
        )
        return
    item["status"] = "unverified"
    try:
        after = await _context(client, port)
        item["after"] = after
        actual = _fingerprint(destination)
        if (
            after["untitled"] is not False
            or os.path.normcase(str(_path(after["projectPath"]).resolve()))
            != os.path.normcase(str(destination.resolve()))
            or not actual
            or actual["size"] <= 0
        ):
            raise ValueError("Saved path/project identity or nonempty PLN not confirmed.")
        before = receipt["target"]["project"]
        if any(after[k] != before[k] for k in ("sessionId", "projectEpoch")):
            raise ValueError("Native session/project changed during save.")
        item["save_verified"] = True
        item["saved_file"] = actual
        if item["archive_path"]:
            source, archived = _path(item["source_path"]), _path(item["archive_path"])
            if _fingerprint(source) != item["previous_file"]:
                raise ValueError("Save succeeded, but previous file changed; not archived.")
            archived.parent.mkdir(exist_ok=True)
            _path(str(archived))
            _move_no_replace(source, archived)
            item["archive_verified"] = (
                not source.exists() and _fingerprint(archived) == item["previous_file"]
            )
            if not item["archive_verified"]:
                raise ValueError("Saved, but archive move could not be verified.")
        item["status"] = "verified"
    except (ArchicadError, ValueError, OSError) as exc:
        item.update(status="verification_failed", error=str(exc))


async def save_project_as(
    client,
    destination_path: str,
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
):
    """Save the current in-memory project as a new explicit PLN; never overwrites."""
    return await write._write(
        client,
        [SaveRequest(destination_path=destination_path)],
        port,
        dry_run,
        confirmation_token,
        "save_project_as",
        planner_override=_plan,
        dispatcher_override=_dispatch,
        completion_note=(
            "Explicit project save. Check per-step verification; saving cannot be undone."
        ),
    )


async def save_next_project_revision(
    client, port: int | None = None, dry_run: bool = True, confirmation_token: str | None = None
):
    """Suggest the next R/REV and archive the previous PLN after verified Save As."""
    return await write._write(
        client,
        [SaveRequest(archive_previous=True)],
        port,
        dry_run,
        confirmation_token,
        "save_next_project_revision",
        planner_override=_plan,
        dispatcher_override=_dispatch,
        completion_note=(
            "Explicit revision save and archival. Check per-step verification; "
            "saving and file moves cannot be undone in Archicad."
        ),
    )


async def inspect_project_save(client, destination_path: str, port: int | None = None):
    """Read context and destination after a receipt/timeout; never retries or archives."""
    port = await resolve_port(client, port)
    context = await _context(client, port)
    destination = _path(destination_path)
    file = _fingerprint(destination)
    matches = bool(
        context["projectPath"]
        and os.path.normcase(str(_path(context["projectPath"]).resolve()))
        == os.path.normcase(str(destination.resolve()))
    )
    return {
        "port": port,
        "project": context,
        "destination_path": str(destination),
        "file": file,
        "current_project_matches": matches,
        "note": (
            "Read-only inspection. A matching path/file does not prove an earlier unknown "
            "operation succeeded; inspect its receipt. No retry or archival performed."
        ),
    }
