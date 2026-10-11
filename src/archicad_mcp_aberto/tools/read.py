"""Read-only tools. None of them changes the model or the selection.

Ported from the LAB bridge v0.3, which was tested against Archicad 29 build 3000
with Tapir 1.7.0.
"""

from __future__ import annotations

import math
from typing import Any, Literal
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


def _same_polygon(a: dict, b: dict) -> bool:
    ac, bc = a.get("coordinates"), b.get("coordinates")
    if not isinstance(ac, list) or not isinstance(bc, list) or len(ac) != len(bc):
        return False
    if {k: v for k, v in a.items() if k != "coordinates"} != {
        k: v for k, v in b.items() if k != "coordinates"
    }:
        return False
    return all(
        x.keys() == y.keys() and all(abs(x[k] - y[k]) <= 1e-9 for k in x)
        for x, y in zip(ac, bc, strict=True)
    )


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
        removed = 0
        for row in rows:
            if not isinstance(row, dict) or "error" in row:
                continue
            unique = []
            for polygon in row.get("floorPlanPolygons", []):
                if any(_same_polygon(polygon, previous) for previous in unique):
                    removed += 1
                else:
                    unique.append(polygon)
            if "floorPlanPolygons" in row:
                row["floorPlanPolygons"] = unique
        if removed:
            result.setdefault("notes", []).append(
                f"Removed {removed} duplicate floor plan polygon(s) within elements "
                "(same vertex order, tolerance 1e-9 m)."
            )
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


async def get_bounding_boxes(
    client: ArchicadClient,
    element_ids: list[str],
    port: int | None = None,
    mode: Literal["2d", "3d"] = "2d",
) -> dict[str, Any]:
    """Read boxes of 1 to 500 elements in metres, preserving order and per-item errors.

    Uses the official JSON API, without Tapir. 2D bounds refer to the floor-plan view;
    3D bounds refer to the 3D view, both relative to the global origin.
    """
    if not 1 <= len(element_ids) <= 500:
        raise ValueError("Pass between 1 and 500 element GUIDs per call.")
    if mode not in ("2d", "3d"):
        raise ValueError("mode must be '2d' or '3d'.")
    guids = [str(UUID(g)).upper() for g in element_ids]
    elements = [{"elementId": {"guid": guid}} for guid in guids]
    port = await resolve_port(client, port)
    dimension = "2D" if mode == "2d" else "3D"
    response = await client.command(port, f"Get{dimension}BoundingBoxes", {"elements": elements})
    rows = response.get(f"boundingBoxes{dimension}")
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected bounding box response cardinality.")
    fields = ["xMin", "yMin", "xMax", "yMax"]
    if mode == "3d":
        fields += ["zMin", "zMax"]
    boxes = []
    for guid, row in zip(guids, rows, strict=True):
        if "error" in row:
            boxes.append({"guid": guid, "error": row["error"]})
        else:
            box = row[f"boundingBox{dimension}"]
            boxes.append({"guid": guid, "box": {field: box[field] for field in fields}})
    return {"port": port, "mode": mode, "boundingBoxes": boxes}


__all__ = [
    "discover_archicad",
    "find_elements",
    "list_library_parts",
    "get_element_details",
    "get_bounding_boxes",
    "get_project_info",
    "get_properties",
    "get_selection",
    "get_stories",
    "list_elements",
    "list_properties",
    "tapir_status",
]


async def find_elements(
    client: ArchicadClient,
    port: int | None = None,
    element_type: str | None = None,
    floor_index: int | None = None,
    layer_index: int | None = None,
    property_guid: str | None = None,
    operator: Literal["equal", "contains", "greater", "less"] = "equal",
    value: str | int | float | bool | None = None,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """Filter elements cheaply first, then paginate matches (up to 500).

    Property comparisons use normal scalar values with no string/number coercion.
    contains is case-sensitive; errors/unavailable values do not match and are reported.
    Detail/property reads use batches of at most 100. No model changes.
    """
    page_args(offset, limit, 500)
    for name, index in (("floor_index", floor_index), ("layer_index", layer_index)):
        if index is not None and (not isinstance(index, int) or isinstance(index, bool)):
            raise ValueError(f"{name} must be an integer.")
    if operator not in {"equal", "contains", "greater", "less"}:
        raise ValueError("Invalid property operator.")
    if property_guid is None and (value is not None or operator != "equal"):
        raise ValueError("Property comparisons require property_guid.")
    if property_guid is not None:
        property_guid = property_ids([property_guid])[0]["propertyId"]["guid"]
        if value is None or not isinstance(value, (str, int, float, bool)):
            raise ValueError("A property filter needs a scalar value.")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Property filter value must be finite.")
        if operator == "contains" and not isinstance(value, str):
            raise ValueError("contains requires a string value.")
        if operator in {"greater", "less"} and (
            not isinstance(value, (int, float)) or isinstance(value, bool)
        ):
            raise ValueError("greater/less require a numeric value.")
    port = await resolve_port(client, port)
    if property_guid is not None:
        available = (await client.command(port, "GetAllPropertyIds")).get("propertyIds", [])
        if property_guid not in {p["propertyId"]["guid"].upper() for p in available}:
            raise ValueError(f"Property {property_guid} does not exist in this project.")
    response = (
        await client.command(port, "GetElementsByType", {"elementType": element_type})
        if element_type
        else await client.command(port, "GetAllElements")
    )
    elements = response["elements"]
    errors = []
    if floor_index is not None or layer_index is not None:
        fields = (["floorIndex"] if floor_index is not None else []) + (
            ["layerIndex"] if layer_index is not None else []
        )
        filtered = []
        for start in range(0, len(elements), 100):
            batch = elements[start : start + 100]
            details = await client.tapir(
                port, "GetDetailsOfElements", {"elements": batch, "fields": fields}
            )
            rows = details.get("detailsOfElements")
            if not isinstance(rows, list) or len(rows) != len(batch):
                raise ValueError("Unexpected details response cardinality.")
            for element, row in zip(batch, rows, strict=True):
                if not isinstance(row, dict) or "error" in row:
                    errors.append({**element, "stage": "details", "error": row})
                elif (floor_index is None or row.get("floorIndex") == floor_index) and (
                    layer_index is None or row.get("layerIndex") == layer_index
                ):
                    filtered.append(element)
        elements = filtered
    if property_guid is not None:
        filtered = []
        for start in range(0, len(elements), 100):
            batch = elements[start : start + 100]
            guids = [e["elementId"]["guid"] for e in batch]
            response = await get_properties(client, guids, [property_guid], port)
            rows = response.get("propertyValuesForElements")
            if not isinstance(rows, list) or len(rows) != len(batch):
                raise ValueError("Unexpected property response cardinality.")
            for element, row in zip(batch, rows, strict=True):
                values = row.get("propertyValues") if isinstance(row, dict) else None
                property_value = (
                    values[0].get("propertyValue")
                    if isinstance(values, list) and len(values) == 1 and isinstance(values[0], dict)
                    else None
                )
                if not isinstance(property_value, dict) or property_value.get("status") != "normal":
                    errors.append({**element, "stage": "property", "error": row})
                    continue
                actual = property_value.get("value")
                numeric = (
                    isinstance(actual, (int, float))
                    and not isinstance(actual, bool)
                    and isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and math.isfinite(actual)
                )
                matches = (
                    (actual == value and (type(actual) is type(value) or numeric))
                    if operator == "equal"
                    else isinstance(actual, str) and value in actual
                    if operator == "contains"
                    else numeric and actual > value
                    if operator == "greater"
                    else numeric and actual < value
                )
                if matches:
                    filtered.append(element)
        elements = filtered
    return {
        "port": port,
        "total": len(elements),
        "offset": offset,
        "elements": elements[offset : offset + limit],
        "errors": errors,
    }


async def _library_inventory(client: ArchicadClient, port: int) -> dict:
    result = await client.tapir(port, "GetAvailableLibraryParts")
    rows, skipped = result.get("libraryParts"), result.get("skippedCount")
    if (
        not isinstance(rows, list)
        or not isinstance(skipped, int)
        or isinstance(skipped, bool)
        or skipped < 0
    ):
        raise ValueError("Unexpected library inventory response.")
    for row in rows:
        if not isinstance(row, dict) or not all(
            isinstance(row.get(key), str) for key in ("guid", "documentName", "fileName", "typeId")
        ):
            raise ValueError("Unexpected library part response.")
        UUID(row["guid"])
        if not isinstance(row.get("index"), int) or isinstance(row["index"], bool):
            raise ValueError("Unexpected library part index.")
    return result


async def list_library_parts(
    client: ArchicadClient,
    port: int | None = None,
    name_contains: str | None = None,
    offset: int = 0,
    limit: int = 100,
) -> dict[str, Any]:
    """List available library parts (GUID/index/name/type), with up to 500 per page.

    Tapir GetAvailableLibraryParts; case-insensitive substring of the display name.
    skippedCount/partial describe unreadable entries: this may be a partial inventory.
    No model changes. GetLibraries lists library containers, not individual parts.
    """
    page_args(offset, limit, 500)
    if name_contains is not None and not isinstance(name_contains, str):
        raise ValueError("name_contains must be a string.")
    port = await resolve_port(client, port)
    response = await _library_inventory(client, port)
    parts = [
        {**row, "name": row["documentName"] or row["fileName"]} for row in response["libraryParts"]
    ]
    if name_contains is not None:
        parts = [p for p in parts if name_contains.casefold() in p["name"].casefold()]
    return {
        "port": port,
        "total": len(parts),
        "offset": offset,
        "libraryParts": parts[offset : offset + limit],
        "partial": response["skippedCount"] > 0,
        "skippedCount": response["skippedCount"],
        "skippedSample": response.get("skippedSample", []),
    }
