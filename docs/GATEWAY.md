# Read-only command gateway

`run_read_command` runs one command from the closed lists below and returns Archicad's
response as it came, without reshaping it. Use it for reads that no dedicated tool covers
yet (hotlinks, issues, IFC data, MEP, design options, revisions and so on). When a
dedicated tool exists, prefer it: those tools validate input and explain their output.

## How to call it

- `command`: `API.<Command>` for the official Archicad JSON API, or `Tapir.<Command>` for
  the Tapir add-on (sent through `API.ExecuteAddOnCommand`). The prefix is required because
  some names exist in both, such as `GetAllElements`.
- `parameters`: the command's own JSON object, sent unchanged (at most 1 MB). Omit it when
  the command takes none.
- `port`: as in every other tool. With several Archicad instances open, the call is
  refused until you pass the port (`resolve_port`).

The response is `{"port", "command", "response"}`. An Archicad or Tapir error is raised
as an error, not returned as data.

## Rules for the lists

- Only names written out here are allowed. Nothing is matched by prefix, so a new command
  in a later Archicad or Tapir stays refused until someone checks it only reads and adds it
  to `tools/gateway.py` and to this page (a unit test keeps the two in step).
- No `Set`, `Create`, `Delete`, `Modify`, `Move`, `Rename`, `Save`, `Execute` or other
  command that changes the model, the project files, the view or the application.
- Left out on purpose from Tapir: `GetPointFromUser` and `GetScriptUIResult` wait for the
  user inside Archicad; `GetUserGSID` and `GetSpecialFolders` expose account and computer
  details that a model read does not need.

## Official JSON API (61 commands)

Source: the `archicad` 30.3000 Python package from Graphisoft (`releases/ac30/b3000commands.py`).
A command that an older Archicad does not have fails with Archicad's own error.

- `API.Get2DBoundingBoxes`
- `API.Get3DBoundingBoxes`
- `API.GetActivePenTables`
- `API.GetAllClassificationSystems`
- `API.GetAllClassificationsInSystem`
- `API.GetAllElements`
- `API.GetAllPropertyGroupIds`
- `API.GetAllPropertyIds`
- `API.GetAllPropertyIdsOfElements`
- `API.GetAllPropertyNames`
- `API.GetAttributeFolderStructure`
- `API.GetAttributeFolders`
- `API.GetAttributesByType`
- `API.GetAttributesCreationInfo`
- `API.GetAttributesIndices`
- `API.GetBuildingMaterialAttributes`
- `API.GetBuiltInContainerNavigatorItems`
- `API.GetClassificationItemAvailability`
- `API.GetClassificationSystemIds`
- `API.GetClassificationSystems`
- `API.GetClassificationsOfElements`
- `API.GetComponentsOfElements`
- `API.GetCompositeAttributes`
- `API.GetDetailNavigatorItems`
- `API.GetDetailsOfClassificationItems`
- `API.GetDetailsOfProperties`
- `API.GetDocument3DNavigatorItems`
- `API.GetElementOwner`
- `API.GetElementsByClassification`
- `API.GetElementsByType`
- `API.GetElementsRelatedToZones`
- `API.GetElevationNavigatorItems`
- `API.GetFillAttributes`
- `API.GetInteriorElevationNavigatorItems`
- `API.GetLayerAttributes`
- `API.GetLayerCombinationAttributes`
- `API.GetLayoutSettings`
- `API.GetLineAttributes`
- `API.GetMEPSystemAttributes`
- `API.GetNavigatorItemTree`
- `API.GetNavigatorItemsType`
- `API.GetOperationProfileAttributes`
- `API.GetPenTableAttributes`
- `API.GetProductInfo`
- `API.GetProfileAttributePreview`
- `API.GetProfileAttributes`
- `API.GetPropertyDefinitionAvailability`
- `API.GetPropertyGroups`
- `API.GetPropertyIds`
- `API.GetPropertyValuesOfElementComponents`
- `API.GetPropertyValuesOfElements`
- `API.GetPublisherSetNames`
- `API.GetSectionNavigatorItems`
- `API.GetSelectedElements`
- `API.GetStoryNavigatorItems`
- `API.GetSurfaceAttributes`
- `API.GetTypesOfElements`
- `API.GetWorksheetNavigatorItems`
- `API.GetZoneCategoryAttributes`
- `API.IsAddOnCommandAvailable`
- `API.IsAlive`

## Tapir 1.7.0 (85 commands)

Source: `RegisterCommand` calls in Tapir 1.7.0 `archicad-addon/Sources/AddOnMain.cpp`.

- `Tapir.FilterElements`
- `Tapir.Get3DBoundingBoxes`
- `Tapir.GetAddOnVersion`
- `Tapir.GetAllElements`
- `Tapir.GetAllProperties`
- `Tapir.GetArchicadLocation`
- `Tapir.GetAttributesByType`
- `Tapir.GetAutoTextKeys`
- `Tapir.GetAutoTextName`
- `Tapir.GetAvailableLibraryParts`
- `Tapir.GetBuildingMaterialPhysicalProperties`
- `Tapir.GetBuildingMaterials`
- `Tapir.GetCalculationUnits`
- `Tapir.GetClassificationsOfElements`
- `Tapir.GetCollisions`
- `Tapir.GetCommentsFromIssue`
- `Tapir.GetComposites`
- `Tapir.GetConnectedElements`
- `Tapir.GetCurrentRevisionChangesOfLayouts`
- `Tapir.GetCurrentWindowType`
- `Tapir.GetDatabaseIdFromNavigatorItemId`
- `Tapir.GetDesignOptionCombinations`
- `Tapir.GetDesignOptionForElements`
- `Tapir.GetDesignOptionSets`
- `Tapir.GetDesignOptions`
- `Tapir.GetDetailsOfElements`
- `Tapir.GetDimensionData`
- `Tapir.GetDocumentRevisions`
- `Tapir.GetElementPreviewImage`
- `Tapir.GetElementTrims`
- `Tapir.GetElementsAttachedToIssue`
- `Tapir.GetElementsByIFCIds`
- `Tapir.GetElementsByType`
- `Tapir.GetElementsOfDesignOptions`
- `Tapir.GetElementsOfGroups`
- `Tapir.GetFavoritePreviewImage`
- `Tapir.GetFavoritesByType`
- `Tapir.GetFills`
- `Tapir.GetGDLParametersOfElements`
- `Tapir.GetGeoLocation`
- `Tapir.GetGroupsOfElements`
- `Tapir.GetHotlinks`
- `Tapir.GetIFCExportTranslators`
- `Tapir.GetIFCIdsOfElements`
- `Tapir.GetIFCPropertiesOfElements`
- `Tapir.GetIFCTypeOfElements`
- `Tapir.GetIssues`
- `Tapir.GetKeynoteAutoTexts`
- `Tapir.GetKeynoteTree`
- `Tapir.GetLayerCombinations`
- `Tapir.GetLayers`
- `Tapir.GetLayoutCustomScheme`
- `Tapir.GetLayoutSettings`
- `Tapir.GetLibraries`
- `Tapir.GetLines`
- `Tapir.GetMEPDistributionSystems`
- `Tapir.GetMEPElements`
- `Tapir.GetMEPPorts`
- `Tapir.GetMEPPreferenceTables`
- `Tapir.GetMEPRoutingElements`
- `Tapir.GetMEPSystems`
- `Tapir.GetModelViewOptions`
- `Tapir.GetNavigatorItemTree`
- `Tapir.GetPenTables`
- `Tapir.GetProfiles`
- `Tapir.GetProjectInfo`
- `Tapir.GetProjectInfoFields`
- `Tapir.GetPropertyValuesOfAttributes`
- `Tapir.GetPropertyValuesOfElements`
- `Tapir.GetRelationsOfElements`
- `Tapir.GetRevisionChanges`
- `Tapir.GetRevisionChangesOfElements`
- `Tapir.GetRevisionIssues`
- `Tapir.GetRoomImage`
- `Tapir.GetSectionElements`
- `Tapir.GetSelectedElements`
- `Tapir.GetSolidElementLinks`
- `Tapir.GetStories`
- `Tapir.GetSubelementsOfHierarchicalElements`
- `Tapir.GetSurfaces`
- `Tapir.GetSuspendGroupsMode`
- `Tapir.GetView2DTransformations`
- `Tapir.GetViewSettings`
- `Tapir.GetZoneBoundaries`
- `Tapir.GetZoneCategories`
