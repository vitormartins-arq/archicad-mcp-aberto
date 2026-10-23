"""Move View Map and Layout Book items into another folder (Tapir 1.7.0 MoveNavigatorItem).

move_navigator_items moves views and folders of the View Map into another View Map
folder, or layouts and subsets of the Layout Book into another subset or the top of the
book. Items and folders are found by name or GUID; a name used more than once needs the
GUID. A folder cannot go into itself or a folder inside it, and an item already in the
folder is refused. Tapir moves one item per call, so the batch runs item by item and the
tree is read back after each move. The item goes to the start of the folder. Never saves.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import drawings, navigator, solids, write

MAX_MOVES = 50
Text = Annotated[str, Field(min_length=1, max_length=255)]
# map -> (Navigator map id, item types that move, folder types that receive, root allowed)
MAPS = {
    "view_map": ("PublicViewMap", None, {"FolderItem"}, False),
    "layout_book": ("LayoutBook", {"LayoutItem", "SubSetItem"}, {"SubSetItem"}, True),
}


class Move(write.InputModel):
    item: Text
    folder: Text

    @field_validator("item", "folder")
    @classmethod
    def trimmed(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("must not start or end with spaces.")
        return value


class MoveRequest(write.InputModel):
    map: Literal["view_map", "layout_book"]
    moves: Annotated[list[Move], Field(min_length=1, max_length=MAX_MOVES)]


def _pick(rows: list[dict], wanted: str, noun: str, index: int) -> dict:
    guid = drawings._as_guid(wanted)
    if guid is not None:
        found = [r for r in rows if r["guid"] == guid]
    else:
        found = [r for r in rows if r["name"].casefold() == wanted.casefold()]
        exact = [r for r in found if r["name"] == wanted]
        found = exact if len(exact) == 1 else found
    if len(found) != 1:
        problem = "is ambiguous (pass its GUID)" if found else "does not exist"
        raise ValueError(f"Move {index}: {noun} {wanted!r} {problem}.")
    return found[0]


def _inside(rows: dict[str, dict], guid: str, ancestor: str) -> bool:
    while guid is not None:
        if guid == ancestor:
            return True
        guid = rows[guid]["parent_guid"]
    return False


async def _plan(client, requests, port, operation):
    (request,) = requests
    map_id, movable, receivers, root_ok = MAPS[request.map]
    port, target, _ = await write._context(client, port)
    tree = await navigator._view_tree(client, port, map_id)
    by_guid = {r["guid"]: r for r in tree}
    items_rows = [r for r in tree if r["depth"] > 0 and (movable is None or r["type"] in movable)]
    folder_rows = [
        r
        for r in tree
        if (r["depth"] > 0 and r["type"] in receivers) or (root_ok and not r["depth"])
    ]
    items, seen = [], set()
    for index, move in enumerate(request.moves):
        item = _pick(items_rows, move.item, "item", index)
        folder = _pick(folder_rows, move.folder, "folder", index)
        if item["guid"] in seen:
            raise ValueError(f"Move {index}: {item['name']!r} is moved twice.")
        seen.add(item["guid"])
        if item["parent_guid"] == folder["guid"]:
            raise ValueError(f"Move {index}: {item['name']!r} is already in {folder['name']!r}.")
        if _inside(by_guid, folder["guid"], item["guid"]):
            raise ValueError(f"Move {index}: {item['name']!r} cannot go inside itself.")
        items.append(
            {
                "index": index,
                "status": "ready",
                "name": item["name"],
                "type": item["type"],
                "from_guid": item["parent_guid"],
                "from_name": by_guid[item["parent_guid"]]["name"],
                "folder_name": folder["name"],
                "parameters": {
                    "navigatorItemIdToMove": {"guid": item["guid"]},
                    "parentNavigatorItemId": {"guid": folder["guid"]},
                },
            }
        )
    return {"operation": operation, "target": target, "map_id": map_id, "items": items}


async def _dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    receipt["undo_scope"] = "Each move is one native command and Undo step."
    for index, item in enumerate(items):
        if not await write._guard_sequential_context(client, receipt, index):
            return
        raw = await solids._results(client, port, "MoveNavigatorItem", item["parameters"], timeout)
        if not isinstance(raw, dict) or not isinstance(raw.get("success"), bool):
            item.update(status="unknown", error=raw if isinstance(raw, str) else str(raw))
            for later in items[index + 1 :]:
                later.update(status="failed", not_attempted=True, error="Stopped: unknown move.")
            receipt["warning"] = "Outcome is unknown. Inspect Archicad; do not retry this plan."
            return
        item["write_response"] = raw
        if not raw["success"]:
            item.update(status="failed", error=raw.get("error", raw))
            continue
        item["status"] = "unverified"
        try:
            rows = {r["guid"]: r for r in await navigator._view_tree(
                client, port, receipt["map_id"], timeout)}  # fmt: skip
        except (ArchicadError, ValueError) as exc:
            receipt["verification_error"] = str(exc)
            continue
        guid = item["parameters"]["navigatorItemIdToMove"]["guid"]
        row = rows.get(guid)
        item["after"] = row
        wanted = item["parameters"]["parentNavigatorItemId"]["guid"]
        ok = row is not None and row["parent_guid"] == wanted
        item["status"] = "verified" if ok else "verification_failed"
        if not ok:
            item["mismatches"] = ["missing" if row is None else "folder"]


async def move_navigator_items(
    client: ArchicadClient,
    map: str,
    moves: list[dict | Move],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 50 moves of View Map or Layout Book items into folders."""
    request = MoveRequest.model_validate(
        {"map": map, "moves": [m.model_dump() if isinstance(m, Move) else m for m in moves]}
    )
    return await write._write(
        client,
        [request],
        port,
        dry_run,
        confirmation_token,
        "move_navigator_items",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
