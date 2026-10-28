"""Read dimensions, model-view options and libraries from Tapir 1.7.0."""

from uuid import UUID

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port

_FOLDER_TYPES = {
    "ApplicationPrefs",
    "GraphisoftPrefs",
    "GraphisoftHome",
    "Cache",
    "Data",
    "UserDocuments",
    "Temporary",
    "Application",
    "Defaults",
    "WebObjects",
    "Templates",
    "Help",
    "EmbeddedProjectLibrary",
    "EmbeddedProjectLibraryHotlink",
    "ProjectPreviews",
}


async def get_dimension_data(
    client: ArchicadClient, element_guids: list[str], port: int | None = None
) -> dict:
    if not 1 <= len(element_guids) <= 100:
        raise ValueError("element_guids must contain between 1 and 100 GUIDs.")
    elements = [{"elementId": {"guid": str(UUID(g)).upper()}} for g in element_guids]
    port = await resolve_port(client, port)
    result = await client.tapir(port, "GetDimensionData", {"elements": elements})
    rows = result.get("dimensionsData")
    if not isinstance(rows, list) or len(rows) != len(elements):
        raise ValueError("Unexpected GetDimensionData response.")
    return {"port": port, "dimensionsData": rows}


async def get_model_view_options(client: ArchicadClient, port: int | None = None) -> dict:
    port = await resolve_port(client, port)
    result = await client.tapir(port, "GetModelViewOptions", {})
    if not isinstance(result.get("modelViewOptions"), list):
        raise ValueError("Unexpected GetModelViewOptions response.")
    return {"port": port, "modelViewOptions": result["modelViewOptions"]}


async def list_libraries(
    client: ArchicadClient, folder_types: list[str] | None = None, port: int | None = None
) -> dict:
    types = folder_types or sorted(_FOLDER_TYPES)
    if not types or len(types) > len(_FOLDER_TYPES) or any(t not in _FOLDER_TYPES for t in types):
        raise ValueError("folder_types contains an unsupported special-folder type.")
    port = await resolve_port(client, port)
    libraries = await client.tapir(port, "GetLibraries", {})
    folders = await client.tapir(port, "GetSpecialFolders", {"folderTypes": types})
    if not isinstance(libraries.get("libraries"), list):
        raise ValueError("Unexpected GetLibraries response.")
    if not isinstance(folders.get("folderPaths"), list) or len(folders["folderPaths"]) != len(
        types
    ):
        raise ValueError("Unexpected GetSpecialFolders response.")
    return {
        "port": port,
        "libraries": libraries["libraries"],
        "specialFolders": [
            {"type": t, "result": r} for t, r in zip(types, folders["folderPaths"], strict=True)
        ],
    }
