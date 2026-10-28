"""Read-only zone queries from Tapir 1.7.0 ElementCommands.cpp."""

from uuid import UUID

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port

_ZONE_READ_LIMIT = 100


def _zone_ids(zone_guids: list[str]) -> tuple[list[str], list[dict]]:
    if not zone_guids or len(zone_guids) > _ZONE_READ_LIMIT:
        raise ValueError("zone_guids must contain between 1 and 100 GUIDs.")
    guids = [str(UUID(g)).upper() for g in zone_guids]
    return guids, [{"elementId": {"guid": g}} for g in guids]


async def get_zone_boundaries(
    client: ArchicadClient, zone_guids: list[str], port: int | None = None
) -> dict:
    """Read boundaries for up to 100 zones; rows stay aligned, including errors."""
    guids, zones = _zone_ids(zone_guids)
    port = await resolve_port(client, port)
    result = await client.tapir(port, "GetZoneBoundaries", {"zones": zones})
    rows = result.get("zoneBoundariesOfZones")
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected GetZoneBoundaries response.")
    return {"port": port, "zoneBoundariesOfZones": rows}


async def get_zone_relations(
    client: ArchicadClient,
    zone_guids: list[str],
    other_element_type: str | None = None,
    port: int | None = None,
) -> dict:
    """Read type-specific relations for up to 100 zones, preserving row errors."""
    guids, elements = _zone_ids(zone_guids)
    port = await resolve_port(client, port)
    parameters: dict = {"elements": elements}
    if other_element_type is not None:
        parameters["otherElementType"] = other_element_type
    result = await client.tapir(port, "GetRelationsOfElements", parameters)
    rows = result.get("relations")
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected GetRelationsOfElements response.")
    return {"port": port, "relations": rows}
