"""Validated, read-only access to the Tapir 1.7.0 hotlink node tree."""

from __future__ import annotations

from uuid import UUID

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port
from archicad_mcp_aberto.tools import read


def _flatten(roots: object) -> list[dict]:
    if not isinstance(roots, list):
        raise ValueError("Unexpected hotlink tree.")
    rows = []
    stack = [(node, None, 0) for node in reversed(roots)]
    seen = set()
    while stack:
        node, parent_guid, depth = stack.pop()
        if not isinstance(node, dict):
            raise ValueError("Unexpected hotlink node.")
        try:
            guid = UUID(node["hotlinkNodeId"]["guid"])
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ValueError("Unexpected hotlink node GUID.") from None
        if not guid.int:
            raise ValueError("Unexpected null hotlink node GUID.")
        guid_text = str(guid).upper()
        if guid_text in seen:
            raise ValueError("Duplicate hotlink node GUID.")
        seen.add(guid_text)
        if (
            not isinstance(node.get("location"), str)
            or not isinstance(node.get("name"), str)
            or node.get("type") not in {"Module", "XRef"}
        ):
            raise ValueError("Unexpected hotlink node details.")
        rows.append(
            {
                "guid": guid_text,
                "name": node["name"],
                "type": node["type"],
                "location": node["location"],
                "parent_guid": parent_guid,
                "depth": depth,
            }
        )
        children = node.get("children", [])
        if not isinstance(children, list):
            raise ValueError("Unexpected hotlink children.")
        stack.extend((child, guid_text, depth + 1) for child in reversed(children))
    return rows


async def list_hotlinks(
    client: ArchicadClient,
    port: int | None = None,
    query: str | None = None,
    offset: int = 0,
    limit: int = 200,
) -> dict:
    """List Module and XRef nodes in tree order, flattened with parent and depth."""
    read.page_args(offset, limit, 500)
    if query is not None and not isinstance(query, str):
        raise ValueError("query must be a string.")
    port = await resolve_port(client, port)
    response = await client.tapir(port, "GetHotlinks")
    rows = _flatten(response.get("hotlinks"))
    if query:
        text = query.casefold()
        rows = [
            row
            for row in rows
            if any(text in row[key].casefold() for key in ("name", "type", "location"))
        ]
    return {
        "port": port,
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "hotlinks": rows[offset : offset + limit],
    }
