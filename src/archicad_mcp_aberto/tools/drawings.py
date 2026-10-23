"""Place existing Navigator views as drawings on existing layouts (Tapir 1.7.0)."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError, TapirError
from archicad_mcp_aberto.tools import documents, write
from archicad_mcp_aberto.tools.read import element_ids

MAX_ITEMS = 20
Name = Annotated[str, Field(min_length=1, max_length=255)]


class DrawingCreate(write.InputModel):
    view_name: Name
    layout_name: Name
    x: float
    y: float
    name: Name | None = None
    name_type: Literal["ViewOrSourceFileName", "ViewIdAndName", "CustomName"] | None = None
    scale: Annotated[float, Field(gt=0)] = 1.0
    angle: float = 0.0
    drawing_scale: Annotated[float, Field(gt=0)] | None = None


async def _plan(client, entries, port, operation):
    port, target, _ = await write._context(client, port)
    views = await documents._tree(client, port, "PublicViewMap")
    layouts = await documents._tree(client, port, "LayoutBook")
    layout_rows = [row for row in layouts if row["type"] == "LayoutItem"]
    layout_dbs = await documents._databases(
        client, port, [row["navigator_guid"] for row in layout_rows]
    )
    items = []
    for index, entry in enumerate(entries):
        source = [row for row in views if row["name"].casefold() == entry.view_name.casefold()]
        layout = [
            row for row in layout_rows if row["name"].casefold() == entry.layout_name.casefold()
        ]
        if len(source) != 1:
            raise ValueError(f"Drawing {index}: view {entry.view_name!r} is missing or ambiguous.")
        if len(layout) != 1:
            raise ValueError(
                f"Drawing {index}: layout {entry.layout_name!r} is missing or ambiguous."
            )
        parameters = {
            "navigatorItemId": {"guid": source[0]["navigator_guid"]},
            "layoutDatabaseId": {"guid": layout_dbs[layout[0]["navigator_guid"]]},
            "position": {"x": entry.x, "y": entry.y},
            "scale": entry.scale,
            "angle": entry.angle,
        }
        if entry.name is not None:
            parameters["name"] = entry.name
            parameters["nameType"] = entry.name_type or "CustomName"
        elif entry.name_type is not None:
            parameters["nameType"] = entry.name_type
        if entry.drawing_scale is not None:
            parameters["drawingScale"] = entry.drawing_scale
        items.append(
            {
                "index": index,
                "status": "ready",
                "view_name": source[0]["name"],
                "layout_name": layout[0]["name"],
                "parameters": parameters,
            }
        )
    return {"operation": operation, "target": target, "items": items}


async def _dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    try:
        raw = await client.tapir(
            port,
            "CreateDrawings",
            {"drawingsData": [item["parameters"] for item in items]},
            timeout=receipt["write_timeout_seconds"],
        )
    except TapirError as exc:
        status = "failed" if exc.detail else "unknown"
        for item in items:
            item.update(status=status, error=exc.detail or str(exc))
        return
    except ArchicadError as exc:
        for item in items:
            item.update(status="unknown", error=str(exc))
        return
    rows = raw.get("elements")
    if not isinstance(rows, list) or len(rows) != len(items):
        for item in items:
            item.update(status="unknown", error="Unexpected response cardinality.")
        return
    created = []
    for item, row in zip(items, rows, strict=True):
        guid = documents._guid(row.get("elementId")) if isinstance(row, dict) else None
        if isinstance(row, dict) and "error" in row:
            item.update(status="failed", error=row["error"])
        elif guid:
            item.update(status="unverified", element_guid=guid)
            created.append(item)
        else:
            item.update(status="unknown", error="Missing element ID or error.")
    if not created:
        return
    try:
        after = await client.tapir(
            port,
            "GetDetailsOfElements",
            {
                "elements": element_ids([item["element_guid"] for item in created]),
                "fields": ["type"],
            },
            timeout=receipt["write_timeout_seconds"],
        )
        details = after.get("detailsOfElements")
        if not isinstance(details, list) or len(details) != len(created):
            raise ValueError("Unexpected verification response cardinality.")
        for item, row in zip(created, details, strict=True):
            item["after"] = row
            item["status"] = "verified" if row.get("type") == "Drawing" else "verification_failed"
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)


async def create_drawings(
    client: ArchicadClient,
    drawings: list[dict | DrawingCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 existing View Map views on existing layouts."""
    if not 1 <= len(drawings) <= MAX_ITEMS:
        raise ValueError(f"Pass between 1 and {MAX_ITEMS} drawings.")
    entries = [
        d if isinstance(d, DrawingCreate) else DrawingCreate.model_validate(d) for d in drawings
    ]
    return await write._write(
        client,
        entries,
        port,
        dry_run,
        confirmation_token,
        "create_drawings",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
