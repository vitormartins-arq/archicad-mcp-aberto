#include "CameraViewCommands.hpp"
#include "CameraAngleConversion.hpp"
#include "CameraCommands.hpp"
#include "OnExit.hpp"

namespace {
// SearchNavigatorItem returned no camera items in AC30 (live test 28/10/2026), so walk the tree.
void CollectCameras (API_NavigatorItem parent, GS::Array<API_NavigatorItem>& items, int depth)
{
    GS::Array<API_NavigatorItem> children;
    if (depth > 16 || ACAPI_Navigator_GetNavigatorChildrenItems (&parent, &children) != NoError) return;
    for (API_NavigatorItem& child : children) {
        if (child.itemType == API_CameraNavItem) items.Push (child);
        else CollectCameras (child, items, depth + 1);
    }
}
GS::Array<API_NavigatorItem> CameraItems (API_NavigatorMapID map)
{
    GS::Array<API_NavigatorItem> items;
    API_NavigatorSet set {};
    set.mapId = map;
    if (ACAPI_Navigator_GetNavigatorSet (&set) != NoError) return items;
    API_NavigatorItem root {};
    root.guid = set.rootGuid;
    root.mapId = map;
    CollectCameras (root, items, 0);
    return items;
}
}

GS::String SaveCameraViewCommand::GetName () const { return "SaveCameraView"; }
GS::Optional<GS::UniString> SaveCameraViewCommand::GetInputParametersSchema () const
{
    return R"({
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Name of the camera and of its View Map item."},
            "folderPath": {"type": "array", "items": {"type": "string"}, "description": "View Map folders, as in Save3DView."},
            "pathName": {"type": "string", "description": "Camera path to append to; created when missing."}
        },
        "additionalProperties": false,
        "required": ["name", "pathName"]
    })";
}
GS::ObjectState SaveCameraViewCommand::Execute (const GS::ObjectState& parameters, GS::ProcessControl&) const
{
    GS::UniString name, pathName;
    parameters.Get ("name", name);
    parameters.Get ("pathName", pathName);
    GS::Array<GS::UniString> folderPath;
    parameters.Get ("folderPath", folderPath);
    bool tooLong = name.GetLength () >= API_UniLongNameLen - 1 || pathName.GetLength () >= API_UniLongNameLen - 1;
    for (const GS::UniString& folder : folderPath) tooLong = tooLong || folder.GetLength () >= API_UniLongNameLen - 1;
    if (tooLong || name.IsEmpty () || pathName.IsEmpty ())
        return CreateErrorResponse (APIERR_BADPARS, "Names must have 1 to 254 characters.");

    API_3DProjectionInfo info {};
    GSErrCode err = ACAPI_View_Get3DProjectionSets (&info);
    if (err != NoError) return CreateErrorResponse (err, "Failed to read the 3D projection.");
    if (!info.isPersp) return CreateErrorResponse (APIERR_BADPARS, "A camera needs a perspective; save parallel views with Save3DView.");

    API_Guid pathGuid = APINULLGuid;
    GS::Array<API_Guid> ids;
    if ((err = ACAPI_Element_GetElemList (API_CamSetID, &ids)) != NoError) return CreateErrorResponse (err, "Failed to read the camera paths.");
    for (const API_Guid& id : ids) {
        API_Element path {};
        path.header.guid = id;
        if (ACAPI_Element_Get (&path) == NoError && GS::UniString (path.camset.name) == pathName) {
            if (pathGuid != APINULLGuid) return CreateErrorResponse (APIERR_BADPARS, "More than one camera path has this name.");
            pathGuid = id;
        }
    }
    API_Guid tail = APINULLGuid;
    if (pathGuid != APINULLGuid) {
        ids.Clear ();
        if ((err = ACAPI_Element_GetElemList (API_CameraID, &ids)) != NoError) return CreateErrorResponse (err, "Failed to read the cameras.");
        for (const API_Guid& id : ids) {
            API_Element camera {};
            camera.header.guid = id;
            if (ACAPI_Element_Get (&camera) == NoError && camera.camera.camSetGuid == pathGuid && camera.camera.perspCam.nextCam == APINULLGuid)
                tail = id;
        }
    }

    API_Guid parentGuid = APINULLGuid;
    GS::UniString folderError;
    if ((err = ResolveViewMapFolder (folderPath, parentGuid, folderError)) != NoError) return CreateErrorResponse (err, folderError);

    // Same element setup as ApplyCameraPath, which was verified live in AC30 (28/10/2026).
    API_Element camera {};
    err = ACAPI_CallUndoableCommand ("Save MCP camera view", [&] () -> GSErrCode {
        if (pathGuid == APINULLGuid) {
            API_Element path {};
            path.header.type = API_CamSetID;
            GS::ucsncpy (path.camset.name, pathName.ToUStr ().Get (), API_UniLongNameLen - 1);
            path.camset.perspPars.openedPath = true;
            path.camset.perspPars.pen = 1;
            path.camset.perspPars.inFrames = 1;
            path.camset.active = false;
            const GSErrCode created = ACAPI_Element_Create (&path, nullptr);
            if (created != NoError) return created;
            pathGuid = path.header.guid;
        }
        camera.header.type = API_CameraID;
        const GSErrCode defaults = ACAPI_Element_GetDefaults (&camera, nullptr);
        if (defaults != NoError) return defaults;
        camera.camera.camSetGuid = pathGuid;
        camera.camera.perspCam.persp = CameraPerspective (info.u.persp);
        camera.camera.perspCam.prevCam = tail;
        camera.camera.perspCam.nextCam = APINULLGuid;
        camera.camera.perspCam.active = true;
        API_ElementMemo memo {};
        memo.elemInfoString = new GS::UniString (name);
        const GS::OnExit freeMemo ([&] { ACAPI_DisposeElemMemoHdls (&memo); });
        return ACAPI_Element_Create (&camera, &memo);
    });
    if (err != NoError) return CreateErrorResponse (err, "Failed to create the camera.");

    // The Project Map lists every camera; camId links the item to the element.
    API_Guid source = APINULLGuid;
    for (const API_NavigatorItem& item : CameraItems (API_ProjectMap))
        if (item.camId == camera.header.guid) source = item.guid;
    if (source == APINULLGuid)
        return CreateErrorResponse (APIERR_GENERAL, "Created the camera but found no Project Map item for it.");
    API_Guid createdGuid = APINULLGuid;
    if ((err = ACAPI_Navigator_CloneProjectMapItemToViewMap (&source, &parentGuid, &createdGuid)) != NoError)
        return CreateErrorResponse (err, "Created the camera but failed to put it in the View Map.");
    API_NavigatorItem created {};
    created.mapId = API_PublicViewMap;
    err = ACAPI_Navigator_GetNavigatorItem (&createdGuid, &created);
    if (err == NoError) {
        SetItemName (created, name);
        err = ACAPI_Navigator_ChangeNavigatorItem (&created);
    }
    if (err != NoError) return CreateErrorResponse (err, "Saved the camera view but failed to name it.");

    // Vitor's rule: camera paths display "None", so cameras do not clutter the plan.
    // Same view option ApplyCameraPath sets (Path Options > Display Options).
    API_ViewOptions options {};
    short modelViewIndex = 0;
    const GS::OnExit freeOptions ([&] { ACAPI_FreeGDLModelViewOptionsPtr (&options.modelViewOpt.gdlOptions); });
    GSErrCode hideError = ACAPI_Navigator_GetViewOptions (&options, &modelViewIndex);
    if (hideError == NoError && options.onScreenViewOpt.camPathViewMode != API_CamPath_None) {
        options.onScreenViewOpt.camPathViewMode = API_CamPath_None;
        hideError = ACAPI_Navigator_ChangeViewOptions (&options, &modelViewIndex);
    }

    return GS::ObjectState ("viewGuid", APIGuidToString (createdGuid), "cameraGuid", APIGuidToString (camera.header.guid),
        "pathGuid", APIGuidToString (pathGuid), "name", name, "folderGuid", APIGuidToString (parentGuid),
        "twoPointLost", info.u.persp.isTwoPointPersp, "pathHiddenInPlan", hideError == NoError);
}

GS::String GetCameraViewsCommand::GetName () const { return "GetCameraViews"; }
GS::Optional<GS::UniString> GetCameraViewsCommand::GetInputParametersSchema () const
{
    return R"({"type": "object", "properties": {}, "additionalProperties": false})";
}
GS::ObjectState GetCameraViewsCommand::Execute (const GS::ObjectState&, GS::ProcessControl&) const
{
    GS::ObjectState response;
    const auto& views = response.AddList<GS::ObjectState> ("views");
    for (const API_NavigatorItem& item : CameraItems (API_PublicViewMap))
        views (GS::ObjectState ("viewGuid", APIGuidToString (item.guid), "name", GS::UniString (item.uName),
            "cameraGuid", APIGuidToString (item.camId)));
    return response;
}
