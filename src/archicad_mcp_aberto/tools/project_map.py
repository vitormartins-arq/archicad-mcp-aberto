"""Project Map folders: read the viewpoint categories and organize their folders.

Uses the companion add-on (R21+): GetProjectMapTree and OrganizeProjectMap.

Live result on Archicad 30 (3001), 14/11/2026, on a copy of a real template: renaming a
native Project Map folder works and its View Map clone follows the new name. Creating a
folder and moving a viewpoint return APIERR_BADPARS in the Project Map, so those steps come
back as "manual" with source and destination for the user to do by hand. A later preview
shows them as "existing" once done. Categories: sections, elevations, interior elevations,
worksheets, details and 3D documents. Moves never cross categories. Never saves.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from archicad_mcp_aberto.connection import ArchicadError, resolve_port
from archicad_mcp_aberto.tools import grids, write

MAX_OPERATIONS = 200
Text = Annotated[str, Field(min_length=1, max_length=255)]


class Operation(write.InputModel):
    action: Literal["create_folder", "rename", "move"]
    key: Text | None = None
    guid: Text | None = None
    parent_guid: Text | None = None
    parent_key: Text | None = None
    name: Text | None = None


class OrganizeRequest(write.InputModel):
    operations: list[Operation]


_ACTIONS = {"create_folder": "createFolder", "rename": "rename", "move": "move"}


def _payload(operations: list[Operation]) -> list[dict]:
    out = []
    for op in operations:
        row = {"action": _ACTIONS[op.action]}
        for field, name in (
            ("key", "key"),
            ("guid", "guid"),
            ("parent_guid", "parentGuid"),
            ("parent_key", "parentKey"),
            ("name", "name"),
        ):
            value = getattr(op, field)
            if value is not None:
                row[name] = value
        out.append(row)
    return out


def _response(raw) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("Invalid answer from the companion add-on; update it to R21 or later.")
    if raw.get("error") and "preview" not in raw:
        error = raw["error"]
        raise ValueError(str(error.get("message", error) if isinstance(error, dict) else error))
    return raw


async def get_project_map(
    client,
    category: str | None = None,
    include_view_map: bool = False,
    port: int | None = None,
) -> dict:
    """Project Map categories, native folders and viewpoints, with View Map clone counts."""
    port = await resolve_port(client, port)
    raw = _response(
        await grids._addon(
            client, port, "GetProjectMapTree", {"includeViewMap": bool(include_view_map)}
        )
    )
    items = raw.get("items") or []
    if category:
        items = [i for i in items if i.get("category") == category]
    result = {"port": port, "items": items}
    if include_view_map:
        result["view_map"] = raw.get("viewMap") or []
    return result


async def _plan(client, requests, port, operation):
    (request,) = requests
    if not request.operations or len(request.operations) > MAX_OPERATIONS:
        raise ValueError(f"Send between 1 and {MAX_OPERATIONS} operations.")
    port = await resolve_port(client, port)
    payload = _payload(request.operations)
    raw = _response(await grids._addon(client, port, "OrganizeProjectMap", {"operations": payload}))
    preview = raw.get("preview") or []
    blocked = [p for p in preview if p.get("status") == "blocked"]
    if blocked:
        reasons = "; ".join(
            f"{p.get('action')} {p.get('to') or p.get('guid')}: {p.get('reason')}" for p in blocked
        )
        raise ValueError(f"Plan refused: {reasons}")
    runnable = [p for p in preview if p.get("status") == "ok"]
    return {
        "operation": operation,
        "target": {"port": port},
        "items": [
            {
                "index": 0,
                "status": "ready" if runnable else "nothing_to_apply",
                "operations": payload,
                "preview": preview,
                "manual_steps": [p for p in preview if p.get("status") == "manual"],
            }
        ],
        "warnings": [
            "Only renames run through the API. Folder creation and moves are listed as manual "
            "steps: Archicad 30 refuses them in the Project Map. No Undo; the project is not saved."
        ],
    }


async def _dispatch(client, receipt):
    item = receipt["items"][0]
    port = receipt["target"]["port"]
    try:
        raw = _response(
            await grids._addon(
                client,
                port,
                "OrganizeProjectMap",
                {"apply": True, "operations": item["operations"]},
                receipt["write_timeout_seconds"],
            )
        )
    except ValueError as exc:
        item.update(status="failed", error=str(exc))
        return
    except ArchicadError as exc:
        item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Outcome unknown. Read the Project Map; never retry this token."
        return
    item["results"] = raw.get("results") or []
    item["verification"] = raw.get("verification") or []
    item["links"] = raw.get("links") or {}
    refused = raw.get("refused") or 0
    if refused:
        item["status"] = "failed"
    elif raw.get("mismatches"):
        item["status"] = "verification_failed"
    else:
        item["status"] = "verified"


async def organize_project_map(
    client,
    operations: list[dict],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
):
    return await write._write(
        client,
        [OrganizeRequest(operations=[Operation(**op) for op in operations])],
        port,
        dry_run,
        confirmation_token,
        "organize_project_map",
        planner_override=_plan,
        dispatcher_override=_dispatch,
        completion_note=(
            "Check verification and links (View Map items and layout drawings before and after). "
            "Do the manual_steps by hand in the Project Map, then preview again."
        ),
    )
