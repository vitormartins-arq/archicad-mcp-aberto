"""Read element structure using Tapir 1.7.0 source schemas."""

from uuid import UUID

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port

_LIMIT = 100


def _ids(guids: list[str], wrapper: str = "elementId") -> list[dict]:
    if not guids or len(guids) > _LIMIT:
        raise ValueError("GUID list must contain between 1 and 100 items.")
    return [{wrapper: {"guid": str(UUID(value)).upper()}} for value in guids]


async def _elements(client, guids, port, command, key):
    elements = _ids(guids)
    port = await resolve_port(client, port)
    result = await client.tapir(port, command, {"elements": elements})
    rows = result.get(key)
    if not isinstance(rows, list) or len(rows) != len(elements):
        raise ValueError(f"Unexpected {command} response.")
    return {"port": port, key: rows}


async def get_subelements(
    client: ArchicadClient, element_guids: list[str], port: int | None = None
) -> dict:
    return await _elements(
        client, element_guids, port, "GetSubelementsOfHierarchicalElements", "subelements"
    )


async def get_element_trims(
    client: ArchicadClient, element_guids: list[str], port: int | None = None
) -> dict:
    return await _elements(client, element_guids, port, "GetElementTrims", "elementTrims")


async def get_solid_operation_links(
    client: ArchicadClient, element_guids: list[str], port: int | None = None
) -> dict:
    return await _elements(client, element_guids, port, "GetSolidElementLinks", "solidLinks")


async def get_section_elements(
    client: ArchicadClient, database_guids: list[str] | None = None, port: int | None = None
) -> dict:
    port = await resolve_port(client, port)
    params = {} if database_guids is None else {"databases": _ids(database_guids, "databaseId")}
    result = await client.tapir(port, "GetSectionElements", params)
    rows = result.get("sectionElements")
    if not isinstance(rows, list):
        raise ValueError("Unexpected GetSectionElements response.")
    return {"port": port, "sectionElements": rows}
