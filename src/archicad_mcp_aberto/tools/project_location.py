"""Read project location, units and layout settings from Tapir 1.7.0."""

from uuid import UUID

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port

_LIMIT = 100


async def get_project_location(client: ArchicadClient, port: int | None = None) -> dict:
    """Read geolocation, survey point and calculation display units."""
    port = await resolve_port(client, port)
    location = await client.tapir(port, "GetGeoLocation", {})
    units = await client.tapir(port, "GetCalculationUnits", {})
    if not isinstance(location.get("projectLocation"), dict):
        raise ValueError("Unexpected GetGeoLocation response.")
    if not all(isinstance(units.get(key), dict) for key in ("length", "area", "volume", "angle")):
        raise ValueError("Unexpected GetCalculationUnits response.")
    return {"port": port, **location, "calculationUnits": units}


async def get_layout_settings(
    client: ArchicadClient, layout_database_guids: list[str], port: int | None = None
) -> dict:
    """Read settings for up to 100 layouts by database GUID, preserving errors."""
    if not layout_database_guids or len(layout_database_guids) > _LIMIT:
        raise ValueError("layout_database_guids must contain between 1 and 100 GUIDs.")
    layouts = [{"databaseId": {"guid": str(UUID(g)).upper()}} for g in layout_database_guids]
    port = await resolve_port(client, port)
    result = await client.tapir(port, "GetLayoutSettings", {"layoutDatabaseIds": layouts})
    rows = result.get("layoutSettings")
    if not isinstance(rows, list) or len(rows) != len(layouts):
        raise ValueError("Unexpected GetLayoutSettings response.")
    return {"port": port, "layoutSettings": rows}
