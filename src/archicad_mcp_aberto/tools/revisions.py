"""Read revision data using Tapir 1.7.0 RevisionCommands.cpp schemas."""

from uuid import UUID

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port

_LIMIT = 100


async def _read(client: ArchicadClient, port: int | None, command: str, key: str) -> dict:
    port = await resolve_port(client, port)
    result = await client.tapir(port, command, {})
    if not isinstance(result.get(key), list):
        raise ValueError(f"Unexpected {command} response.")
    return {"port": port, key: result[key]}


async def list_document_revisions(client: ArchicadClient, port: int | None = None) -> dict:
    return await _read(client, port, "GetDocumentRevisions", "documentRevisions")


async def list_revision_issues(client: ArchicadClient, port: int | None = None) -> dict:
    return await _read(client, port, "GetRevisionIssues", "revisionIssues")


def _ids(guids: list[str] | None, wrapper: str) -> list[dict] | None:
    if guids is None:
        return None
    if not guids or len(guids) > _LIMIT:
        raise ValueError("Each GUID list must contain between 1 and 100 items.")
    return [{wrapper: {"guid": str(UUID(g)).upper()}} for g in guids]


async def get_revision_changes(
    client: ArchicadClient,
    element_guids: list[str] | None = None,
    layout_database_guids: list[str] | None = None,
    port: int | None = None,
) -> dict:
    """List all changes and optionally aligned changes for elements and layouts."""
    elements = _ids(element_guids, "elementId")
    layouts = _ids(layout_database_guids, "databaseId")
    port = await resolve_port(client, port)
    all_changes = await client.tapir(port, "GetRevisionChanges", {})
    rows = all_changes.get("revisionChanges")
    if not isinstance(rows, list):
        raise ValueError("Unexpected GetRevisionChanges response.")
    response = {"port": port, "revisionChanges": rows}
    if elements is not None:
        result = await client.tapir(port, "GetRevisionChangesOfElements", {"elements": elements})
        values = result.get("revisionChangesOfElements")
        if not isinstance(values, list) or len(values) != len(elements):
            raise ValueError("Unexpected GetRevisionChangesOfElements response.")
        response["revisionChangesOfElements"] = values
    if layouts is not None:
        result = await client.tapir(
            port, "GetCurrentRevisionChangesOfLayouts", {"layoutDatabaseIds": layouts}
        )
        values = result.get("currentRevisionChangesOfLayouts")
        if not isinstance(values, list) or len(values) != len(layouts):
            raise ValueError("Unexpected GetCurrentRevisionChangesOfLayouts response.")
        response["currentRevisionChangesOfLayouts"] = values
    return response
