"""Detailed, read-only attribute access through Tapir 1.7.0."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port

AttributeKind = Literal[
    "composites",
    "profiles",
    "surfaces",
    "building_material_physics",
    "zone_categories",
    "pen_tables",
    "lines",
    "fills",
]
MAX_ATTRIBUTES = 500
BATCH = 100
KINDS = {
    "composites": ("Composite", "GetComposites", "composites"),
    "profiles": ("Profile", "GetProfiles", "profiles"),
    "surfaces": ("Surface", "GetSurfaces", "surfaces"),
    "building_material_physics": (
        "BuildingMaterial",
        "GetBuildingMaterialPhysicalProperties",
        "properties",
    ),
    "zone_categories": ("ZoneCategory", "GetZoneCategories", "zoneCategories"),
    "pen_tables": ("PenTable", "GetPenTables", "penTables"),
    "lines": ("Line", "GetLines", "lines"),
    "fills": ("Fill", "GetFills", "fills"),
}


async def get_attribute_details(
    client: ArchicadClient,
    kind: AttributeKind,
    guids: list[str] | None = None,
    port: int | None = None,
) -> dict:
    """Read up to 500 attributes of one closed-list kind; errors remain per item."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {', '.join(KINDS)}.")
    port = await resolve_port(client, port)
    attribute_type, command, response_key = KINDS[kind]
    if guids is None:
        raw = await client.tapir(port, "GetAttributesByType", {"attributeType": attribute_type})
        headers = raw.get("attributes")
        if not isinstance(headers, list):
            raise ValueError("Unexpected attribute inventory response.")
        values = [row.get("attributeId", {}).get("guid") for row in headers]
    else:
        if not isinstance(guids, list):
            raise ValueError("guids must be a list or null.")
        values = guids
    if len(values) > MAX_ATTRIBUTES:
        raise ValueError(f"At most {MAX_ATTRIBUTES} attribute GUIDs are allowed.")
    normalized = []
    for value in values:
        try:
            guid = UUID(value)
        except (TypeError, ValueError, AttributeError):
            raise ValueError("Invalid attribute GUID.") from None
        if not guid.int:
            raise ValueError("Attribute GUID must not be null.")
        text = str(guid).upper()
        if text not in normalized:
            normalized.append(text)
    items = []
    for offset in range(0, len(normalized), BATCH):
        batch = normalized[offset : offset + BATCH]
        response = await client.tapir(
            port, command, {"attributeIds": [{"attributeId": {"guid": guid}} for guid in batch]}
        )
        rows = response.get(response_key)
        if not isinstance(rows, list) or len(rows) != len(batch):
            raise ValueError(f"Unexpected {command} response cardinality.")
        for guid, row in zip(batch, rows, strict=True):
            if not isinstance(row, dict):
                raise ValueError(f"Unexpected {command} response item.")
            if "error" in row:
                items.append({"guid": guid, "error": row["error"]})
                continue
            returned = row.get("attributeId", {}).get("guid")
            if returned is not None and str(UUID(returned)).upper() != guid:
                raise ValueError(f"{command} response GUID does not match the request.")
            items.append({"guid": guid, "details": row})
    return {"port": port, "kind": kind, "total": len(items), "items": items}
