"""List Interactive Schedules with their Project Map folder, saved views and layouts.

Read-only. Archicad 30 exposes no schedule scheme through any API (see the companion
add-on's docs/INTERACTIVE_SCHEDULES.md), so this works only from the Navigator:

- a Project Map ScheduleItem is the schedule itself; its source GUID is the scheme;
- a View Map ScheduleItem with the same source GUID is a saved view of that schedule;
- a Layout Book DrawingItem whose source GUID is that view is the schedule placed on
  the layout that contains the drawing.
"""

from __future__ import annotations

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port
from archicad_mcp_aberto.tools.navigator import get_navigator_tree

SCHEDULE = "ScheduleItem"
LAYOUT = "LayoutItem"
DRAWING = "DrawingItem"


async def _rows(client: ArchicadClient, port: int, navigator_map: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        page = await get_navigator_tree(client, navigator_map, port, None, offset, 500)
        rows.extend(page["items"])
        offset += len(page["items"])
        if not page["items"] or offset >= page["total"]:
            return rows


def _label(row: dict) -> str:
    return " ".join(x for x in (row.get("uiId") or row.get("prefix"), row["name"]) if x).strip()


def _paths(rows: list[dict]) -> dict[str, list[str]]:
    """Folder labels from the top (root excluded) down to each row's parent."""
    by_guid = {r["guid"]: r for r in rows}
    out: dict[str, list[str]] = {}
    for row in rows:
        chain = []
        parent = row.get("parent_guid")
        while parent and parent in by_guid:
            node = by_guid[parent]
            if node.get("parent_guid") is not None:
                chain.append(_label(node))
            parent = node.get("parent_guid")
        out[row["guid"]] = list(reversed(chain))
    return out


def _layout_of(row: dict, by_guid: dict[str, dict]) -> dict | None:
    parent = row.get("parent_guid")
    while parent and parent in by_guid:
        node = by_guid[parent]
        if node["type"] == LAYOUT:
            return node
        parent = node.get("parent_guid")
    return None


async def list_schedules(
    client: ArchicadClient,
    port: int | None = None,
    query: str | None = None,
    only_on_layouts: bool = False,
) -> dict:
    """List Project Map schedules with folder, saved views and the layouts they are on."""
    port = await resolve_port(client, port)
    project = await _rows(client, port, "ProjectMap")
    views = await _rows(client, port, "PublicViewMap")
    book = await _rows(client, port, "LayoutBook")
    project_paths, view_paths, book_paths = _paths(project), _paths(views), _paths(book)
    book_by_guid = {r["guid"]: r for r in book}

    placements: dict[str, list[dict]] = {}
    for drawing in book:
        if drawing["type"] != DRAWING or not drawing.get("source_guid"):
            continue
        layout = _layout_of(drawing, book_by_guid)
        placements.setdefault(drawing["source_guid"], []).append(
            {
                "drawing_guid": drawing["guid"],
                "drawing_name": drawing["name"],
                "layout_guid": layout["guid"] if layout else None,
                "layout": _label(layout) if layout else None,
                "subset": " / ".join(book_paths[layout["guid"]]) if layout else None,
            }
        )

    views_by_scheme: dict[str | None, list[dict]] = {}
    for view in views:
        if view["type"] != SCHEDULE:
            continue
        views_by_scheme.setdefault(view.get("source_guid"), []).append(view)

    text = query.casefold() if query else None
    schedules = []
    for item in project:
        if item["type"] != SCHEDULE:
            continue
        folder = " / ".join(project_paths[item["guid"]])
        if text and not any(
            text in s.casefold() for s in (item["name"], item.get("uiId") or "", folder)
        ):
            continue
        saved = []
        layouts: list[dict] = []
        for view in (
            views_by_scheme.get(item.get("source_guid"), []) if item.get("source_guid") else []
        ):
            placed = placements.get(view["guid"], [])
            saved.append(
                {
                    "guid": view["guid"],
                    "name": view["name"],
                    "folder": " / ".join(view_paths[view["guid"]]),
                    "layout_count": len(placed),
                }
            )
            layouts.extend(placed)
        if only_on_layouts and not layouts:
            continue
        schedules.append(
            {
                "guid": item["guid"],
                "id": item.get("uiId") or "",
                "name": item["name"],
                "folder": folder,
                "scheme_guid": item.get("source_guid"),
                "views": saved,
                "layouts": layouts,
            }
        )
    return {
        "port": port,
        "total": len(schedules),
        "on_layouts": sum(1 for s in schedules if s["layouts"]),
        "schedules": schedules,
        "note": (
            "From the Navigator only: Archicad 30 exposes no schedule fields, criteria "
            "or values through the API. A schedule reaches a layout through a saved view."
        ),
    }
