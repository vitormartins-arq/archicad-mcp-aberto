"""Read publisher set outputs and publish one set to an explicit folder."""

from __future__ import annotations

from pathlib import Path

from archicad_mcp_aberto.connection import ArchicadError, resolve_port
from archicad_mcp_aberto.tools import grids, write


class PublishRequest(write.InputModel):
    publisher_set_name: str
    output_folder: str


def _folder(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or any(c in value for c in "\x00\n\r"):
        raise ValueError("An absolute output folder is required.")
    if not path.is_dir():
        raise ValueError(f"Output folder does not exist: {path}")
    return path


def _files(folder: Path) -> dict:
    return {
        str(p.relative_to(folder)): p.stat().st_mtime_ns for p in folder.rglob("*") if p.is_file()
    }


async def _sets(client, port) -> list[dict]:
    raw = await grids._addon(client, port, "GetPublisherSets")
    sets = raw.get("sets") if isinstance(raw, dict) else None
    if not isinstance(sets, list):
        raise ValueError("Invalid publisher set list; update the companion add-on.")
    return sets


async def list_publisher_sets(client, port: int | None = None) -> dict:
    port = await resolve_port(client, port)
    return {
        "port": port,
        "sets": await _sets(client, port),
        "note": "The Archicad API can read this saved output but has no call to change it.",
    }


async def _plan(client, requests, port, operation):
    (request,) = requests
    port = await resolve_port(client, port)
    folder = _folder(request.output_folder)
    matches = [s for s in await _sets(client, port) if s.get("name") == request.publisher_set_name]
    if len(matches) != 1:
        raise ValueError(f"Publisher set not found or ambiguous: {request.publisher_set_name}")
    return {
        "operation": operation,
        "target": {"port": port},
        "items": [
            {
                "index": 0,
                "status": "ready",
                "publisher_set_name": request.publisher_set_name,
                "root_guid": matches[0]["rootGuid"],
                "saved_path_before": matches[0].get("path"),
                "output_folder": str(folder),
            }
        ],
        "warnings": ["Publishing can replace same-named files in the output folder; no Undo."],
    }


async def _dispatch(client, receipt):
    item = receipt["items"][0]
    port = receipt["target"]["port"]
    try:
        folder = _folder(item["output_folder"])
        before = _files(folder)
        await grids._addon(
            client,
            port,
            "PublishPublisherSet",
            {"rootGuid": item["root_guid"], "outputPath": str(folder)},
            receipt["write_timeout_seconds"],
        )
    except (ValueError, OSError) as exc:
        item.update(status="failed", error=str(exc))
        return
    except ArchicadError as exc:
        item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Publish outcome unknown. Inspect the folder; never retry this token."
        return
    after = _files(folder)
    item["files_written"] = sorted(n for n, t in after.items() if before.get(n) != t)
    try:
        rows = await _sets(client, port)
        item["saved_path_after"] = next(
            s.get("path") for s in rows if s.get("rootGuid") == item["root_guid"]
        )
    except (ArchicadError, ValueError, StopIteration) as exc:
        item["saved_path_after_error"] = str(exc)
    item["status"] = "verified" if item["files_written"] else "unverified"


async def publish_publisher_set(
    client,
    publisher_set_name: str,
    output_folder: str,
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
):
    return await write._write(
        client,
        [PublishRequest(publisher_set_name=publisher_set_name, output_folder=output_folder)],
        port,
        dry_run,
        confirmation_token,
        "publish_publisher_set",
        planner_override=_plan,
        dispatcher_override=_dispatch,
        completion_note="Check files_written and saved_path_after; publishing has no Undo.",
    )
