"""Place views on layouts as Drawings (Tapir 1.7.0 CreateDrawings).

create_drawings puts a view of the View Map (or a viewpoint of the Project Map) on an
existing layout of the Layout Book. The preview finds the view and the layout in the
Navigator and refuses what Tapir cannot place: folders, layouts, master layouts and
already placed Drawings (Tapir checks this too, because such a source terminates
Archicad inside element creation). The position is the Drawing's centre on the layout,
in metres of paper. The read-back lists the Drawings of the layout's database
(GetElementsByType with databases). Tapir switches the window to the layout.
update_drawings updates every Drawing on the given layouts (UpdateDrawings, Archicad 27
and later). Tapir answers only success or failure and Archicad has no read-back of a
Drawing's update state, so a successful update stays unverified. Never saves.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import documents, solids, write

MAX_DRAWINGS = 20
Text = Annotated[str, Field(min_length=1, max_length=255)]
# Navigator item types Tapir 1.7.0 accepts as a Drawing source (IsPlaceableAsDrawing).
PLACEABLE = {
    "StoryItem",
    "SectionItem",
    "ElevationItem",
    "InteriorElevationItem",
    "DetailDrawingItem",
    "WorksheetDrawingItem",
    "DocumentFrom3DItem",
    "PerspectiveItem",
    "AxonometryItem",
    "ScheduleItem",
    "ListItem",
    "TextListItem",
    "TocItem",
}


class DrawingCreate(write.InputModel):
    view: Text
    layout: Text
    position: write.Point
    name: Text | None = None
    angle: float | None = None

    @field_validator("view", "layout", "name")
    @classmethod
    def trimmed(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError("must not start or end with spaces.")
        return value


def _as_guid(value: str) -> str | None:
    try:
        return str(UUID(value)).upper()
    except ValueError:
        return None


def _find(rows: list[dict], wanted: str, types: set[str], noun: str, index: int) -> dict:
    guid = _as_guid(wanted)
    if guid is not None:
        found = [r for r in rows if r["navigator_guid"] == guid]
    else:
        found = [r for r in rows if str(r["name"]).casefold() == wanted.casefold()]
        exact = [r for r in found if r["name"] == wanted]
        found = exact if len(exact) == 1 else found
    if guid is None:
        found = [r for r in found if r["type"] in types]
    if len(found) != 1:
        problem = "is ambiguous (pass its GUID)" if found else "does not exist"
        raise ValueError(f"Drawing {index}: {noun} {wanted!r} {problem}.")
    if found[0]["type"] not in types:
        raise ValueError(
            f"Drawing {index}: {noun} {wanted!r} is a {found[0]['type']}, which cannot be used."
        )
    return found[0]


async def _plan(client, drawings, port, operation):
    port, target, _ = await write._context(client, port)
    views = await documents._tree(client, port, "PublicViewMap")
    project = await documents._tree(client, port, "ProjectMap")
    layouts = await documents._tree(client, port, "LayoutBook")
    wanted = {}
    for index, drawing in enumerate(drawings):
        # A name is looked up in the View Map; a GUID in either map.
        sources = views + project if _as_guid(drawing.view) else views
        view = _find(sources, drawing.view, PLACEABLE, "view", index)
        layout = _find(layouts, drawing.layout, {"LayoutItem"}, "layout", index)
        wanted[index] = (view, layout)
    databases = await documents._databases(
        client, port, sorted({layout["navigator_guid"] for _, layout in wanted.values()})
    )
    items = []
    for index, drawing in enumerate(drawings):
        view, layout = wanted[index]
        database = databases.get(layout["navigator_guid"])
        if database is None:
            raise ValueError(f"Drawing {index}: cannot find the database of {layout['name']!r}.")
        parameters: dict[str, Any] = {
            "navigatorItemId": {"guid": view["navigator_guid"]},
            "layoutDatabaseId": {"guid": database},
            "position": drawing.position.model_dump(),
        }
        if drawing.name is not None:
            parameters["name"] = drawing.name
        if drawing.angle is not None:
            parameters["angle"] = drawing.angle
        items.append(
            {
                "index": index,
                "status": "ready",
                "view_name": view["name"],
                "view_type": view["type"],
                "layout_name": layout["name"],
                "parameters": parameters,
            }
        )
    return {"operation": operation, "target": target, "items": items}


async def _layout_drawings(client, port, database, timeout) -> set[str]:
    response = await client.tapir(
        port,
        "GetElementsByType",
        {"elementType": "Drawing", "databases": [{"databaseId": {"guid": database}}]},
        timeout=timeout,
    )
    results = response.get("executionResultForDatabases")
    if not isinstance(results, list) or len(results) != 1 or not results[0].get("success"):
        raise ValueError(f"Cannot list the Drawings of the layout ({results}).")
    rows = response.get("elements")
    if not isinstance(rows, list):
        raise ValueError("Unexpected Drawing list response.")
    return {g for g in (documents._guid(r.get("elementId")) for r in rows if isinstance(r, dict))}


async def _dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    try:
        raw = await client.tapir(
            port,
            "CreateDrawings",
            {"drawingsData": [i["parameters"] for i in items]},
            timeout=timeout,
        )
    except ArchicadError as exc:
        for item in items:
            item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Outcome is unknown. Inspect Archicad; do not retry this plan."
        return
    receipt["raw_response"] = raw
    rows = raw.get("elements")
    if not isinstance(rows, list) or len(rows) != len(items):
        for item in items:
            item.update(status="unknown", error="Unexpected response cardinality.")
        return
    created = []
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        guid = documents._guid(row.get("elementId")) if isinstance(row, dict) else None
        if isinstance(row, dict) and "error" in row:
            item.update(status="failed", error=row["error"])
        elif guid:
            item.update(status="unverified", drawing_guid=guid)
            created.append(item)
        else:
            item.update(status="unknown", error="Missing element ID or error; inspect Archicad.")
    placed: dict[str, set[str]] = {}
    for item in created:
        database = item["parameters"]["layoutDatabaseId"]["guid"]
        try:
            if database not in placed:
                placed[database] = await _layout_drawings(client, port, database, timeout)
        except (ArchicadError, ValueError) as exc:
            receipt["verification_error"] = str(exc)
            return
        found = item["drawing_guid"] in placed[database]
        item["status"] = "verified" if found else "verification_failed"
        if not found:
            item["mismatches"] = ["not on the layout"]


async def create_drawings(
    client: ArchicadClient,
    drawings: list[dict | DrawingCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 Drawings: a view (View Map name or Navigator GUID) placed
    on an existing layout (name or GUID) at a position in metres of paper."""
    if not 1 <= len(drawings) <= MAX_DRAWINGS:
        raise ValueError(f"Pass between 1 and {MAX_DRAWINGS} drawings.")
    validated = [
        d if isinstance(d, DrawingCreate) else DrawingCreate.model_validate(d) for d in drawings
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_drawings",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )


class LayoutsUpdate(write.InputModel):
    layouts: Annotated[list[Text], Field(min_length=1, max_length=MAX_DRAWINGS)]


async def _update_plan(client, requests, port, operation):
    (request,) = requests
    port, target, _ = await write._context(client, port)
    tree = await documents._tree(client, port, "LayoutBook")
    layouts = []
    for index, wanted in enumerate(request.layouts):
        layout = _find(tree, wanted, {"LayoutItem"}, "layout", index)
        if any(row["navigator_guid"] == layout["navigator_guid"] for row in layouts):
            raise ValueError(f"Drawing {index}: layout {wanted!r} appears twice.")
        layouts.append(layout)
    databases = await documents._databases(client, port, [r["navigator_guid"] for r in layouts])
    items = []
    for layout in layouts:
        database = databases.get(layout["navigator_guid"])
        if database is None:
            raise ValueError(f"Cannot find the database of {layout['name']!r}.")
        guids = sorted(g for g in await _layout_drawings(client, port, database, None) if g)
        if not guids:
            raise ValueError(f"Layout {layout['name']!r} has no Drawings.")
        items += [
            {
                "index": len(items) + offset,
                "status": "ready",
                "layout_name": layout["name"],
                "layout_database": database,
                "drawing_guid": guid,
            }
            for offset, guid in enumerate(guids)
        ]
    return {"operation": operation, "target": target, "items": items}


async def _update_dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    raw = await solids._results(
        client, port, "UpdateDrawings",
        {"elements": [{"elementId": {"guid": i["drawing_guid"]}} for i in items]},
        receipt["write_timeout_seconds"],
    )  # fmt: skip
    if not isinstance(raw, dict) or not isinstance(raw.get("success"), bool):
        return solids._unknown(receipt, raw if isinstance(raw, str) else "Unexpected response.")
    receipt["raw_response"] = raw
    for item in items:
        if raw["success"]:
            item["status"] = "unverified"
        else:
            item.update(status="failed", error=raw.get("error", raw))
    if raw["success"]:
        receipt["verification_note"] = (
            "Archicad has no read-back of a Drawing's update state; look at the layouts."
        )


async def update_drawings(
    client: ArchicadClient,
    layouts: list[str],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply updating every Drawing on up to 20 layouts (name or GUID)."""
    request = LayoutsUpdate.model_validate({"layouts": layouts})
    return await write._write(
        client,
        [request],
        port,
        dry_run,
        confirmation_token,
        "update_drawings",
        planner_override=_update_plan,
        dispatcher_override=_update_dispatch,
    )
