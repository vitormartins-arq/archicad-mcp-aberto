"""Read-only command gateway: any listed official JSON API or Tapir read command, raw.

The lists are closed on purpose. A name is allowed only if it is written out below;
nothing is matched by prefix, so a new Archicad or Tapir command stays refused until
someone checks it reads and adds it here and in docs/GATEWAY.md.
"""

from __future__ import annotations

import json
from typing import Any

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port

MAX_PARAMETER_BYTES = 1_000_000

# Official JSON API, from the `archicad` 30.3000 Python package (releases/ac30/b3000).
OFFICIAL_READ_COMMANDS = frozenset(
    {
        "Get2DBoundingBoxes",
        "Get3DBoundingBoxes",
        "GetActivePenTables",
        "GetAllClassificationSystems",
        "GetAllClassificationsInSystem",
        "GetAllElements",
        "GetAllPropertyGroupIds",
        "GetAllPropertyIds",
        "GetAllPropertyIdsOfElements",
        "GetAllPropertyNames",
        "GetAttributeFolderStructure",
        "GetAttributeFolders",
        "GetAttributesByType",
        "GetAttributesCreationInfo",
        "GetAttributesIndices",
        "GetBuildingMaterialAttributes",
        "GetBuiltInContainerNavigatorItems",
        "GetClassificationItemAvailability",
        "GetClassificationSystemIds",
        "GetClassificationSystems",
        "GetClassificationsOfElements",
        "GetComponentsOfElements",
        "GetCompositeAttributes",
        "GetDetailNavigatorItems",
        "GetDetailsOfClassificationItems",
        "GetDetailsOfProperties",
        "GetDocument3DNavigatorItems",
        "GetElementOwner",
        "GetElementsByClassification",
        "GetElementsByType",
        "GetElementsRelatedToZones",
        "GetElevationNavigatorItems",
        "GetFillAttributes",
        "GetInteriorElevationNavigatorItems",
        "GetLayerAttributes",
        "GetLayerCombinationAttributes",
        "GetLayoutSettings",
        "GetLineAttributes",
        "GetMEPSystemAttributes",
        "GetNavigatorItemTree",
        "GetNavigatorItemsType",
        "GetOperationProfileAttributes",
        "GetPenTableAttributes",
        "GetProductInfo",
        "GetProfileAttributePreview",
        "GetProfileAttributes",
        "GetPropertyDefinitionAvailability",
        "GetPropertyGroups",
        "GetPropertyIds",
        "GetPropertyValuesOfElementComponents",
        "GetPropertyValuesOfElements",
        "GetPublisherSetNames",
        "GetSectionNavigatorItems",
        "GetSelectedElements",
        "GetStoryNavigatorItems",
        "GetSurfaceAttributes",
        "GetTypesOfElements",
        "GetWorksheetNavigatorItems",
        "GetZoneCategoryAttributes",
        "IsAddOnCommandAvailable",
        "IsAlive",
    }
)

# Tapir 1.7.0, from RegisterCommand in AddOnMain.cpp. Left out on purpose:
# GetPointFromUser and GetScriptUIResult wait for the user in Archicad, and
# GetUserGSID and GetSpecialFolders expose account and computer details.
TAPIR_READ_COMMANDS = frozenset(
    {
        "FilterElements",
        "Get3DBoundingBoxes",
        "GetAddOnVersion",
        "GetAllElements",
        "GetAllProperties",
        "GetArchicadLocation",
        "GetAttributesByType",
        "GetAutoTextKeys",
        "GetAutoTextName",
        "GetAvailableLibraryParts",
        "GetBuildingMaterialPhysicalProperties",
        "GetBuildingMaterials",
        "GetCalculationUnits",
        "GetClassificationsOfElements",
        "GetCollisions",
        "GetCommentsFromIssue",
        "GetComposites",
        "GetConnectedElements",
        "GetCurrentRevisionChangesOfLayouts",
        "GetCurrentWindowType",
        "GetDatabaseIdFromNavigatorItemId",
        "GetDesignOptionCombinations",
        "GetDesignOptionForElements",
        "GetDesignOptionSets",
        "GetDesignOptions",
        "GetDetailsOfElements",
        "GetDimensionData",
        "GetDocumentRevisions",
        "GetElementPreviewImage",
        "GetElementTrims",
        "GetElementsAttachedToIssue",
        "GetElementsByIFCIds",
        "GetElementsByType",
        "GetElementsOfDesignOptions",
        "GetElementsOfGroups",
        "GetFavoritePreviewImage",
        "GetFavoritesByType",
        "GetFills",
        "GetGDLParametersOfElements",
        "GetGeoLocation",
        "GetGroupsOfElements",
        "GetHotlinks",
        "GetIFCExportTranslators",
        "GetIFCIdsOfElements",
        "GetIFCPropertiesOfElements",
        "GetIFCTypeOfElements",
        "GetIssues",
        "GetKeynoteAutoTexts",
        "GetKeynoteTree",
        "GetLayerCombinations",
        "GetLayers",
        "GetLayoutCustomScheme",
        "GetLayoutSettings",
        "GetLibraries",
        "GetLines",
        "GetMEPDistributionSystems",
        "GetMEPElements",
        "GetMEPPorts",
        "GetMEPPreferenceTables",
        "GetMEPRoutingElements",
        "GetMEPSystems",
        "GetModelViewOptions",
        "GetNavigatorItemTree",
        "GetPenTables",
        "GetProfiles",
        "GetProjectInfo",
        "GetProjectInfoFields",
        "GetPropertyValuesOfAttributes",
        "GetPropertyValuesOfElements",
        "GetRelationsOfElements",
        "GetRevisionChanges",
        "GetRevisionChangesOfElements",
        "GetRevisionIssues",
        "GetRoomImage",
        "GetSectionElements",
        "GetSelectedElements",
        "GetSolidElementLinks",
        "GetStories",
        "GetSubelementsOfHierarchicalElements",
        "GetSurfaces",
        "GetSuspendGroupsMode",
        "GetView2DTransformations",
        "GetViewSettings",
        "GetZoneBoundaries",
        "GetZoneCategories",
    }
)


def _split(command: str) -> tuple[str, str]:
    source, _, name = command.partition(".")
    allowed = {"API": OFFICIAL_READ_COMMANDS, "Tapir": TAPIR_READ_COMMANDS}.get(source)
    if allowed is None or not name:
        raise ValueError(
            "Name the command as 'API.<Command>' (official JSON API) or "
            "'Tapir.<Command>' (Tapir add-on), for example 'Tapir.GetDetailsOfElements'."
        )
    if name not in allowed:
        raise ValueError(
            f"{command!r} is not on the read-only list (see docs/GATEWAY.md). "
            "Writes and unchecked commands are refused."
        )
    return source, name


async def run_read_command(
    client: ArchicadClient,
    command: str,
    parameters: dict[str, Any] | None = None,
    port: int | None = None,
) -> dict:
    """Run one listed read-only command and return Archicad's response as it came.

    command is 'API.<Command>' or 'Tapir.<Command>'; parameters go through unchanged.
    """
    source, name = _split(command)
    if parameters is not None:
        if not isinstance(parameters, dict):
            raise ValueError("parameters must be a JSON object.")
        size = len(json.dumps(parameters, allow_nan=False).encode())
        if size > MAX_PARAMETER_BYTES:
            raise ValueError(f"parameters must be at most {MAX_PARAMETER_BYTES} bytes as JSON.")
    port = await resolve_port(client, port)
    if source == "API":
        response = await client.command(port, name, parameters)
    else:
        response = await client.tapir(port, name, parameters)
    return {"port": port, "command": command, "response": response}
