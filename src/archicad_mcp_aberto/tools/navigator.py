"""Flattened Navigator read access through Tapir 1.7.0 GetNavigatorItemTree."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port
from archicad_mcp_aberto.tools import read

NavigatorMap = Literal["ProjectMap", "PublicViewMap", "LayoutBook", "PublisherSets"]
MAPS = ("ProjectMap", "PublicViewMap", "LayoutBook", "PublisherSets")


def _flatten(root: object) -> list[dict]:
    """Preorder traversal preserving native order, with no recursive Python calls."""
    out = []
    stack = [(root, None, 0)]
    while stack:
        node, parent, depth = stack.pop()
        if not isinstance(node, dict):
            raise ValueError("Unexpected navigator node.")
        identifier = node.get("navigatorItemId")
        try:
            guid = str(UUID(identifier["guid"])).upper()
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ValueError("Unexpected navigator item ID.") from None
        if not isinstance(node.get("name"), str) or not isinstance(node.get("type"), str):
            raise ValueError("Unexpected navigator name or type.")
        out.append(
            {
                "guid": guid,
                "name": node["name"],
                "type": node["type"],
                "parent_guid": parent,
                "depth": depth,
                "prefix": node.get("prefix"),
                "uiId": node.get("uiId"),
            }
        )
        children = node.get("children", [])
        if not isinstance(children, list):
            raise ValueError("Unexpected navigator children.")
        for wrapper in reversed(children):
            if not isinstance(wrapper, dict) or "navigatorItem" not in wrapper:
                raise ValueError("Unexpected navigator child wrapper.")
            stack.append((wrapper["navigatorItem"], guid, depth + 1))
    return out


async def get_navigator_tree(
    client: ArchicadClient,
    navigator_map: NavigatorMap = "ProjectMap",
    port: int | None = None,
    query: str | None = None,
    offset: int = 0,
    limit: int = 200,
    publisher_set_name: str | None = None,
) -> dict:
    """Read a flattened Navigator map, root included at depth 0; never writes.

    Maps: ProjectMap, PublicViewMap, LayoutBook, PublisherSets. Query matches name,
    type or displayed uiId (case-insensitive), before pagination. Parent/depth remain
    relative to the unfiltered tree. PublisherSets returns one set: the exact named
    publisher_set_name, or the first native set when omitted (not all publisher sets).
    """
    if navigator_map not in MAPS:
        raise ValueError(f"navigator_map must be one of {', '.join(MAPS)}.")
    if type(offset) is not int or type(limit) is not int:
        raise ValueError("offset and limit must be integers.")
    read.page_args(offset, limit, 500)
    if publisher_set_name is not None:
        if navigator_map != "PublisherSets":
            raise ValueError("publisher_set_name is only accepted for PublisherSets.")
        if not isinstance(publisher_set_name, str) or not publisher_set_name.strip():
            raise ValueError("publisher_set_name must not be blank.")
    port = await resolve_port(client, port)
    parameters = {"navigatorMapId": navigator_map}
    if publisher_set_name is not None:
        parameters["publisherSetName"] = publisher_set_name
    response = await client.tapir(port, "GetNavigatorItemTree", parameters)
    rows = _flatten(response.get("navigatorItemTree"))
    if query:
        text = query.casefold()
        rows = [
            r
            for r in rows
            if any(
                isinstance(r[k], str) and text in r[k].casefold() for k in ("name", "type", "uiId")
            )
        ]
    result = {
        "port": port,
        "navigator_map": navigator_map,
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "items": rows[offset : offset + limit],
    }
    if navigator_map == "PublisherSets":
        result["publisher_set_name"] = publisher_set_name
        if publisher_set_name is None:
            result["note"] = (
                "Tapir returns the first publisher set only; "
                "pass publisher_set_name for another set."
            )
    return result
