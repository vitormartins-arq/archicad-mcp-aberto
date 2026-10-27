#include "PlanViewCommands.hpp"
#include "CameraCommands.hpp"

#include <cstring>

// Frees what ACAPI_Navigator_GetNavigatorView allocates.
static void DisposeView (API_NavigatorView& view)
{
    delete view.modelViewOpt;
    view.modelViewOpt = nullptr;
    delete view.layerStats;
    view.layerStats = nullptr;
    delete view.dimPrefs;
    view.dimPrefs = nullptr;
}

static GS::ObjectState ViewToObjectState (const API_NavigatorView& view)
{
    GS::ObjectState os ("saveZoom", view.saveZoom, "saveDrawingScale", view.saveDScale, "saveLayers", view.saveLaySet);
    if (view.saveZoom) {
        os.Add ("zoom", GS::ObjectState ("xMin", view.zoom.xMin, "yMin", view.zoom.yMin, "xMax", view.zoom.xMax, "yMax", view.zoom.yMax));
    }
    if (view.saveDScale) {
        os.Add ("drawingScale", view.drawingScale);
    }
    if (view.saveLaySet) {
        os.Add ("layerCombination", GS::UniString (view.layerCombination, CC_UTF8));
    }
    return os;
}

GS::String SaveStoryViewCommand::GetName () const
{
    return "SaveStoryView";
}

GS::Optional<GS::UniString> SaveStoryViewCommand::GetInputParametersSchema () const
{
    return R"({
        "type": "object",
        "properties": {
            "storyIndex": {"type": "integer", "description": "Floor index of the story whose floor plan is saved."},
            "name": {"type": "string", "minLength": 1, "maxLength": 200, "description": "Name of the new view."},
            "folderPath": {
                "type": "array",
                "description": "View Map folders, as in Save3DView. The first is searched anywhere in the View Map, the others below it; missing ones are created.",
                "items": {"type": "string", "minLength": 1, "maxLength": 200},
                "maxItems": 10
            },
            "zoom": {
                "type": "object",
                "description": "Zoom box of the view in model coordinates (metres).",
                "properties": {
                    "xMin": {"type": "number"}, "yMin": {"type": "number"},
                    "xMax": {"type": "number"}, "yMax": {"type": "number"}
                },
                "additionalProperties": false,
                "required": ["xMin", "yMin", "xMax", "yMax"]
            },
            "drawingScale": {"type": "integer", "minimum": 1, "maximum": 100000, "description": "Scale denominator, 25 for 1:25. Left out: the story's own setting."},
            "layerCombination": {"type": "string", "minLength": 1, "maxLength": 255, "description": "Name of an existing layer combination. Left out: the story's own setting."}
        },
        "additionalProperties": false,
        "required": ["storyIndex", "name", "zoom"]
    })";
}

GS::ObjectState SaveStoryViewCommand::Execute (const GS::ObjectState& parameters, GS::ProcessControl& /*processControl*/) const
{
    Int32 storyIndex = 0;
    parameters.Get ("storyIndex", storyIndex);
    GS::UniString name;
    parameters.Get ("name", name);
    GS::Array<GS::UniString> folderPath;
    parameters.Get ("folderPath", folderPath);
    GS::ObjectState zoomOS;
    parameters.Get ("zoom", zoomOS);
    API_Box zoom {};
    zoomOS.Get ("xMin", zoom.xMin);
    zoomOS.Get ("yMin", zoom.yMin);
    zoomOS.Get ("xMax", zoom.xMax);
    zoomOS.Get ("yMax", zoom.yMax);
    if (zoom.xMax - zoom.xMin < 0.01 || zoom.yMax - zoom.yMin < 0.01) {
        return CreateErrorResponse (APIERR_BADPARS, "The zoom box must be at least 0.01 m wide and deep.");
    }
    bool tooLong = name.GetLength () >= API_UniLongNameLen - 1;
    for (const GS::UniString& folder : folderPath) {
        tooLong = tooLong || folder.GetLength () >= API_UniLongNameLen - 1;
    }
    GS::UniString layerCombination;
    const bool hasLayers = parameters.Get ("layerCombination", layerCombination);
    if (tooLong || (hasLayers && layerCombination.GetLength () >= API_AttrNameLen - 1)) {
        return CreateErrorResponse (APIERR_BADPARS, "Names must be shorter than 255 characters.");
    }

    // The Project Map's story item; its clone in the View Map is a floor plan view.
    API_NavigatorItem search {};
    search.mapId = API_ProjectMap;
    search.itemType = API_StoryNavItem;
    GS::Array<API_NavigatorItem> stories;
    GSErrCode err = ACAPI_Navigator_SearchNavigatorItem (&search, &stories);
    if (err != NoError) {
        return CreateErrorResponse (err, "Failed to read the stories of the Project Map.");
    }
    const API_NavigatorItem* story = nullptr;
    for (const API_NavigatorItem& item : stories) {
        if (item.floorNum == storyIndex) {
            story = &item;
            break;
        }
    }
    if (story == nullptr) {
        return CreateErrorResponse (APIERR_BADPARS, GS::UniString::Printf ("Story %d is not in the Project Map.", (int) storyIndex));
    }

    API_Guid parentGuid = APINULLGuid;
    GS::UniString folderError;
    err = ResolveViewMapFolder (folderPath, parentGuid, folderError);
    if (err != NoError) {
        return CreateErrorResponse (err, folderError);
    }

    API_Guid createdGuid = APINULLGuid;
    err = ACAPI_Navigator_CloneProjectMapItemToViewMap (&story->guid, &parentGuid, &createdGuid);
    if (err != NoError) {
        return CreateErrorResponse (err, "Failed to save the story view in the View Map.");
    }

    API_NavigatorItem created {};
    created.mapId = API_PublicViewMap;
    err = ACAPI_Navigator_GetNavigatorItem (&createdGuid, &created);
    API_NavigatorView view {};
    if (err == NoError) {
        SetItemName (created, name);
        err = ACAPI_Navigator_GetNavigatorView (&created, &view);
    }
    if (err == NoError) {
        view.zoom = zoom;
        view.saveZoom = true;
        Int32 scale = 0;
        if (parameters.Get ("drawingScale", scale)) {
            view.drawingScale = scale;
            view.saveDScale = true;
        }
        if (hasLayers) {
            // A named combination replaces the stored layer states.
            delete view.layerStats;
            view.layerStats = nullptr;
            strncpy (view.layerCombination, layerCombination.ToCStr (0, MaxUSize, CC_UTF8).Get (), API_AttrNameLen - 1);
            view.layerCombination[API_AttrNameLen - 1] = '\0';
            view.saveLaySet = true;
        }
        err = ACAPI_Navigator_ChangeNavigatorView (&created, &view);
    }
    DisposeView (view);
    if (err != NoError) {
        GS::ObjectState error = CreateErrorResponse (err, "Saved the story view but failed to name it or set its zoom, scale or layers.");
        error.Add ("viewGuid", APIGuidToString (createdGuid));
        return error;
    }

    API_NavigatorView after {};
    err = ACAPI_Navigator_GetNavigatorView (&created, &after);
    GS::ObjectState response ("viewGuid", APIGuidToString (createdGuid), "name", name, "storyIndex", storyIndex);
    if (!folderPath.IsEmpty ()) {
        response.Add ("folderGuid", APIGuidToString (parentGuid));
    }
    if (err == NoError) {
        response.Add ("view", ViewToObjectState (after));
    }
    DisposeView (after);
    return response;
}
