"""Read-only tools. None of them changes the model or the selection.

Ported from the LAB bridge v0.3, which was tested against Archicad 29 build 3000
with Tapir 1.7.0.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from archicad_mcp_aberto.connection import (
    ArchicadClient,
    ArchicadError,
    discover,
    resolve_port,
)
from archicad_mcp_aberto.connection.discovery import tapir_state

MAX_ELEMENTS_PER_CALL = 100
MAX_PROPERTIES_PER_CALL = 30
DETAIL_FIELDS = (
    "type",
    "id",
    "floorIndex",
    "layerIndex",
    "drawIndex",
    "details",
    "hotlinkId",
    "floorPlanPolygons",
)
# floorPlanPolygons can regenerate 2D drawing primitives and dominate the call time.
DEFAULT_DETAIL_FIELDS = [f for f in DETAIL_FIELDS if f != "floorPlanPolygons"]


def element_ids(guids: list[str]) -> list[dict[str, Any]]:
    if not 1 <= len(guids) <= MAX_ELEMENTS_PER_CALL:
        raise ValueError(f"Pass between 1 and {MAX_ELEMENTS_PER_CALL} element GUIDs per call.")
    return [{"elementId": {"guid": str(UUID(g)).upper()}} for g in guids]


def property_ids(guids: list[str]) -> list[dict[str, Any]]:
    if not 1 <= len(guids) <= MAX_PROPERTIES_PER_CALL:
        raise ValueError(f"Pass between 1 and {MAX_PROPERTIES_PER_CALL} property GUIDs per call.")
    return [{"propertyId": {"guid": str(UUID(g)).upper()}} for g in guids]


def page_args(offset: int, limit: int, max_limit: int) -> None:
    if offset < 0 or not 1 <= limit <= max_limit:
        raise ValueError(f"offset must be >= 0 and limit between 1 and {max_limit}.")


async def discover_archicad(client: ArchicadClient) -> dict[str, Any]:
    found = await discover(client)
    for item in found:
        if item["status"] != "ready":
            continue
        try:
            all_elements = await client.command(item["port"], "GetAllElements")
            selected = await client.command(item["port"], "GetSelectedElements")
        except ArchicadError as exc:
            item["detail"] = str(exc)
            continue
        item["element_count"] = len(all_elements.get("elements", []))
        item["selected_count"] = len(selected.get("elements", []))
    return {"instances": found, "status": "connected" if found else "waiting_for_archicad"}


async def list_elements(
    client: ArchicadClient,
    port: int | None = None,
    element_type: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    page_args(offset, limit, 500)
    port = await resolve_port(client, port)
    if element_type:
        result = await client.command(port, "GetElementsByType", {"elementType": element_type})
    else:
        result = await client.command(port, "GetAllElements")
    elements = result.get("elements", [])
    return {
        "port": port,
        "total": len(elements),
        "offset": offset,
        "elements": elements[offset : offset + limit],
    }


async def get_selection(client: ArchicadClient, port: int | None = None) -> dict[str, Any]:
    port = await resolve_port(client, port)
    return {"port": port, **await client.command(port, "GetSelectedElements")}


async def list_properties(
    client: ArchicadClient, port: int | None = None, offset: int = 0, limit: int = 100
) -> dict[str, Any]:
    page_args(offset, limit, 200)
    port = await resolve_port(client, port)
    # Archicad 29/30 return the list under "propertyIds" (verified live on AC30 build 3001).
    properties = (await client.command(port, "GetAllPropertyIds")).get("propertyIds", [])
    page = properties[offset : offset + limit]
    details = (
        await client.command(port, "GetDetailsOfProperties", {"properties": page}) if page else {}
    )
    return {"port": port, "total": len(properties), "offset": offset, **details}


async def get_properties(
    client: ArchicadClient,
    element_guids: list[str],
    property_guids: list[str],
    port: int | None = None,
) -> dict[str, Any]:
    elements = element_ids(element_guids)
    properties = property_ids(property_guids)
    port = await resolve_port(client, port)
    result = await client.command(
        port, "GetPropertyValuesOfElements", {"elements": elements, "properties": properties}
    )
    return {"port": port, "elements": elements, "properties": properties, **result}


async def tapir_status(client: ArchicadClient) -> dict[str, Any]:
    found = await discover(client, identify=False)
    for item in found:
        if item["status"] == "busy":
            item["tapir_loaded"] = None
            continue
        item.update(await tapir_state(client, item["port"]))
    return {"instances": found, "status": "connected" if found else "waiting_for_archicad"}


async def get_project_info(client: ArchicadClient, port: int | None = None) -> dict[str, Any]:
    port = await resolve_port(client, port)
    return {"port": port, **await client.tapir(port, "GetProjectInfo")}


async def get_stories(client: ArchicadClient, port: int | None = None) -> dict[str, Any]:
    port = await resolve_port(client, port)
    return {"port": port, **await client.tapir(port, "GetStories")}


async def get_element_details(
    client: ArchicadClient,
    element_guids: list[str],
    port: int | None = None,
    fields: list[str] | None = None,
) -> dict[str, Any]:
    elements = element_ids(element_guids)
    requested = list(dict.fromkeys(fields if fields is not None else DEFAULT_DETAIL_FIELDS))
    invalid = [f for f in requested if f not in DETAIL_FIELDS]
    if not requested or invalid:
        raise ValueError(
            f"Invalid detail fields {invalid or '[]'}. Valid fields: {', '.join(DETAIL_FIELDS)}."
        )
    port = await resolve_port(client, port)
    result = await client.tapir(
        port, "GetDetailsOfElements", {"elements": elements, "fields": requested}
    )
    if "floorPlanPolygons" in requested:
        # Tapir 1.7.0 only reports polygons it finds inside a cut fill of the element's floor
        # plan symbol, and leaves the key out otherwise. Say so instead of letting the
        # missing key read as a failure.
        rows = result.get("detailsOfElements", [])
        missing = [
            r
            for r in rows
            if isinstance(r, dict) and "error" not in r and "floorPlanPolygons" not in r
        ]
        for row in missing:
            row["floorPlanPolygons"] = []
        if missing:
            result["note"] = (
                f"{len(missing)} element(s) returned no floor plan polygons. Tapir only "
                "returns the polygons of a cut fill (walls, slabs, columns and other "
                "construction elements cut by the floor plan). An element with no cut fill "
                "on this story, an empty fill or a type outside that list returns none."
            )
    return {"port": port, "fields": requested, **result}


__all__ = [
    "discover_archicad",
    "get_element_details",
    "get_project_info",
    "get_properties",
    "get_selection",
    "get_stories",
    "list_elements",
    "list_properties",
    "tapir_status",
]
