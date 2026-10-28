"""Read IFC metadata using Tapir 1.7.0 IFCCommands.cpp schemas."""

from uuid import UUID

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port

_LIMIT = 100


async def get_ifc_of_elements(
    client: ArchicadClient, element_guids: list[str], port: int | None = None
) -> dict:
    """Read IFC type, IDs and properties for up to 100 elements, preserving row errors."""
    if not element_guids or len(element_guids) > _LIMIT:
        raise ValueError("element_guids must contain between 1 and 100 GUIDs.")
    elements = [{"elementId": {"guid": str(UUID(g)).upper()}} for g in element_guids]
    port = await resolve_port(client, port)
    response: dict = {"port": port}
    for command, key in (
        ("GetIFCTypeOfElements", "elementIFCTypes"),
        ("GetIFCIdsOfElements", "elementIFCIds"),
        ("GetIFCPropertiesOfElements", "elementIFCProperties"),
    ):
        result = await client.tapir(port, command, {"elements": elements})
        rows = result.get(key)
        if not isinstance(rows, list) or len(rows) != len(elements):
            raise ValueError(f"Unexpected {command} response.")
        response[key] = rows
    return response


async def find_elements_by_ifc_ids(
    client: ArchicadClient, ifc_ids: list[str], port: int | None = None
) -> dict:
    """Find elements for up to 100 IFC GlobalIds; each input keeps its own output row."""
    if not ifc_ids or len(ifc_ids) > _LIMIT:
        raise ValueError("ifc_ids must contain between 1 and 100 values.")
    if any(not isinstance(value, str) or not value.strip() for value in ifc_ids):
        raise ValueError("IFC IDs must be non-empty strings.")
    values = [value.strip() for value in ifc_ids]
    port = await resolve_port(client, port)
    result = await client.tapir(port, "GetElementsByIFCIds", {"ifcIds": values})
    rows = result.get("elementsByIFCIds")
    if not isinstance(rows, list) or len(rows) != len(values):
        raise ValueError("Unexpected GetElementsByIFCIds response.")
    return {"port": port, "elementsByIFCIds": rows}
