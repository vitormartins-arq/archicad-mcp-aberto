#include "CameraCommands.hpp"

#ifdef ServerMainVers_3000
#include "NativeImage.hpp"
#include "MemoryOChannel32.hpp"
#include "Base64Converter.hpp"
#endif

#include <cmath>

// Archicad keeps the view angles in degrees (live test, AC30 build 3001, 21/10/2026):
// the perspective azimuth is atan2 (camera - target) in 0..360, the view cone is 60 by
// default. The MCP speaks radians, so these commands convert at the edge. The roll
// angle is assumed to be in degrees too; it was 0 in every test.

static const double DefaultViewConeDeg = 60.0;
static const double Pi = 3.14159265358979323846;

static double ToRadians (double degrees)
{
    return degrees * Pi / 180.0;
}

static double ToDegrees (double radians)
{
    return radians * 180.0 / Pi;
}

static GS::ObjectState Point3D (const API_Coord& c, double z)
{
    return GS::ObjectState ("x", c.x, "y", c.y, "z", z);
}

static bool GetPoint3D (const GS::ObjectState& parameters, const char* name, API_Coord& c, double& z)
{
    const GS::ObjectState* point = parameters.Get (name);
    if (point == nullptr) {
        return false;
    }
    return point->Get ("x", c.x) && point->Get ("y", c.y) && point->Get ("z", z);
}

static GS::ObjectState ProjectionToObjectState (const API_3DProjectionInfo& info)
{
    GS::ObjectState os;
    os.Add ("isPerspective", info.isPersp);
    os.Add ("linkedToCamera", info.camGuid != APINULLGuid || info.actCamSet != APINULLGuid);
    if (info.isPersp) {
        const API_PerspPars& p = info.u.persp;
        os.Add ("camera", Point3D (p.pos, p.cameraZ));
        os.Add ("target", Point3D (p.target, p.targetZ));
        os.Add ("viewCone", ToRadians (p.viewCone));
        os.Add ("rollAngle", ToRadians (p.rollAngle));
        os.Add ("distance", p.distance);
        os.Add ("azimuth", ToRadians (p.azimuth));
        os.Add ("twoPointPerspective", p.isTwoPointPersp);
    } else {
        const API_AxonoPars& a = info.u.axono;
        os.Add ("azimuth", ToRadians (a.azimuth));
        os.Add ("projectionMode", static_cast<Int32> (a.projMod));
    }
    return os;
}

GS::String Get3DCameraCommand::GetName () const
{
    return "Get3DCamera";
}

GS::Optional<GS::UniString> Get3DCameraCommand::GetInputParametersSchema () const
{
    return R"({
        "type": "object",
        "properties": {},
        "additionalProperties": false
    })";
}

GS::ObjectState Get3DCameraCommand::Execute (const GS::ObjectState& /*parameters*/, GS::ProcessControl& /*processControl*/) const
{
    API_3DProjectionInfo info {};
    const GSErrCode err = ACAPI_View_Get3DProjectionSets (&info);
    if (err != NoError) {
        return CreateErrorResponse (err, "Failed to read the 3D projection.");
    }
    return ProjectionToObjectState (info);
}

GS::String Set3DCameraCommand::GetName () const
{
    return "Set3DCamera";
}

GS::Optional<GS::UniString> Set3DCameraCommand::GetInputParametersSchema () const
{
    return R"({
        "type": "object",
        "properties": {
            "perspective": {
                "type": "object",
                "description": "Perspective camera, in metres; the view cone in radians (converted to Archicad's degrees, default 60 degrees).",
                "properties": {
                    "camera": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "z": {"type": "number"}}, "required": ["x", "y", "z"]},
                    "target": {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}, "z": {"type": "number"}}, "required": ["x", "y", "z"]},
                    "viewCone": {"type": "number", "exclusiveMinimum": 0.0, "exclusiveMaximum": 3.14159},
                    "twoPointPerspective": {"type": "boolean"}
                },
                "additionalProperties": false,
                "required": ["camera", "target"]
            },
            "parallel": {
                "type": "object",
                "description": "Parallel projection: azimuth in radians (converted to Archicad's degrees) and Archicad's projection mode number.",
                "properties": {
                    "azimuth": {"type": "number"},
                    "projectionMode": {"type": "integer"}
                },
                "additionalProperties": false
            }
        },
        "additionalProperties": false,
        "oneOf": [{"required": ["perspective"]}, {"required": ["parallel"]}]
    })";
}

GS::ObjectState Set3DCameraCommand::Execute (const GS::ObjectState& parameters, GS::ProcessControl& /*processControl*/) const
{
    API_3DProjectionInfo info {};
    GSErrCode err = ACAPI_View_Get3DProjectionSets (&info);
    if (err != NoError) {
        return CreateErrorResponse (err, "Failed to read the 3D projection.");
    }

    const GS::ObjectState* perspective = parameters.Get ("perspective");
    const GS::ObjectState* parallel = parameters.Get ("parallel");
    if (perspective != nullptr) {
        API_Coord camera {};
        API_Coord target {};
        double cameraZ = 0.0;
        double targetZ = 0.0;
        if (!GetPoint3D (*perspective, "camera", camera, cameraZ) || !GetPoint3D (*perspective, "target", target, targetZ)) {
            return CreateErrorResponse (APIERR_BADPARS, "camera and target need x, y and z.");
        }
        const double dx = target.x - camera.x;
        const double dy = target.y - camera.y;
        const double dz = targetZ - cameraZ;
        const double distance = std::sqrt (dx * dx + dy * dy + dz * dz);
        if (distance < 0.01) {
            return CreateErrorResponse (APIERR_BADPARS, "camera and target must be at least 0.01 m apart.");
        }
        // A free camera, not tied to a floor plan Camera element.
        info.camGuid = APINULLGuid;
        info.actCamSet = APINULLGuid;
        const bool wasPerspective = info.isPersp;
        info.isPersp = true;
        API_PerspPars& p = info.u.persp;
        if (!wasPerspective) {
            // u.persp still holds the parallel settings: start from sane defaults.
            p = API_PerspPars {};
            p.viewCone = DefaultViewConeDeg;
            p.isTwoPointPersp = false;
        }
        p.pos = camera;
        p.target = target;
        p.cameraZ = cameraZ;
        p.targetZ = targetZ;
        p.distance = distance;
        double azimuth = ToDegrees (std::atan2 (camera.y - target.y, camera.x - target.x));
        if (azimuth < 0.0) {
            azimuth += 360.0;
        }
        p.azimuth = azimuth;
        p.rollAngle = 0.0;
        double viewCone = 0.0;
        if (perspective->Get ("viewCone", viewCone)) {
            p.viewCone = ToDegrees (viewCone);
        } else if (!(p.viewCone > 0.0 && p.viewCone < 180.0)) {
            p.viewCone = DefaultViewConeDeg;
        }
        // Not inherited from the previous camera: a level camera is the photographic default.
        p.isTwoPointPersp = false;
        perspective->Get ("twoPointPerspective", p.isTwoPointPersp);
    } else if (parallel != nullptr) {
        if (info.isPersp) {
            // Switch kind first so u.axono holds Archicad's own parallel settings.
            info.isPersp = false;
            bool switchOnly = true;
            err = ACAPI_View_Change3DProjectionSets (&info, &switchOnly);
            if (err != NoError) {
                return CreateErrorResponse (err, "Failed to switch to a parallel projection.");
            }
            err = ACAPI_View_Get3DProjectionSets (&info);
            if (err != NoError) {
                return CreateErrorResponse (err, "Failed to read the 3D projection.");
            }
        }
        API_AxonoPars& a = info.u.axono;
        double azimuth = 0.0;
        if (parallel->Get ("azimuth", azimuth)) {
            a.azimuth = ToDegrees (azimuth);
        }
        Int32 mode = a.projMod;
        if (parallel->Get ("projectionMode", mode)) {
            a.projMod = static_cast<short> (mode);
        }
    } else {
        return CreateErrorResponse (APIERR_BADPARS, "Give perspective or parallel.");
    }

    err = ACAPI_View_Change3DProjectionSets (&info, nullptr);
    if (err != NoError) {
        return CreateErrorResponse (err, "Failed to change the 3D projection.");
    }

    API_3DProjectionInfo after {};
    err = ACAPI_View_Get3DProjectionSets (&after);
    if (err != NoError) {
        return CreateErrorResponse (err, "Changed the 3D projection but failed to read it back.");
    }
    return ProjectionToObjectState (after);
}

GS::String Save3DViewCommand::GetName () const
{
    return "Save3DView";
}

GS::Optional<GS::UniString> Save3DViewCommand::GetInputParametersSchema () const
{
    return R"({
        "type": "object",
        "properties": {
            "name": {"type": "string", "minLength": 1, "maxLength": 200, "description": "Name of the new view."},
            "folderPath": {
                "type": "array",
                "description": "View Map folders, e.g. [\"02 | MODELO 3D\", \"AMBIENTES\", \"RECEPCAO\"]. The first is searched anywhere in the View Map, the others below it; missing ones are created (the first at the top level).",
                "items": {"type": "string", "minLength": 1, "maxLength": 200},
                "maxItems": 10
            }
        },
        "additionalProperties": false,
        "required": ["name"]
    })";
}

static void SetItemName (API_NavigatorItem& item, const GS::UniString& name)
{
    GS::ucscpy (item.uName, name.ToUStr ().Get ());
    item.customName = true;
}

static GSErrCode FindOrCreateFolder (const API_Guid& parentGuid, const GS::UniString& folder, API_Guid& folderGuid)
{
    API_NavigatorItem root {};
    root.guid = parentGuid;
    root.mapId = API_PublicViewMap;
    GS::Array<API_NavigatorItem> children;
    GSErrCode err = ACAPI_Navigator_GetNavigatorChildrenItems (&root, &children);
    if (err != NoError) {
        return err;
    }
    for (const API_NavigatorItem& child : children) {
        if (child.itemType == API_FolderNavItem && GS::UniString (child.uName) == folder) {
            folderGuid = child.guid;
            return NoError;
        }
    }
    API_NavigatorItem newFolder {};
    newFolder.mapId = API_PublicViewMap;
    newFolder.itemType = API_FolderNavItem;
    SetItemName (newFolder, folder);
    const GS::Guid parent = APIGuid2GSGuid (parentGuid);
    err = ACAPI_Navigator_NewNavigatorView (&newFolder, nullptr, &parent, nullptr);
    if (err == NoError) {
        folderGuid = newFolder.guid;
    }
    return err;
}

// Depth-first search of the View Map for a folder by name, so the first folder of a path
// may sit below the project's own top folder (live test: "02 | MODELO 3D" was inside
// "TEMPLATE LAB COCADA").
static bool FindFolderAnywhere (const API_Guid& parentGuid, const GS::UniString& folder, API_Guid& folderGuid, int depth = 0)
{
    if (depth > 8) {
        return false;
    }
    API_NavigatorItem parent {};
    parent.guid = parentGuid;
    parent.mapId = API_PublicViewMap;
    GS::Array<API_NavigatorItem> children;
    if (ACAPI_Navigator_GetNavigatorChildrenItems (&parent, &children) != NoError) {
        return false;
    }
    for (const API_NavigatorItem& child : children) {
        if (child.itemType == API_FolderNavItem && GS::UniString (child.uName) == folder) {
            folderGuid = child.guid;
            return true;
        }
    }
    for (const API_NavigatorItem& child : children) {
        if (child.itemType == API_FolderNavItem && FindFolderAnywhere (child.guid, folder, folderGuid, depth + 1)) {
            return true;
        }
    }
    return false;
}

GS::ObjectState Save3DViewCommand::Execute (const GS::ObjectState& parameters, GS::ProcessControl& /*processControl*/) const
{
    GS::UniString name;
    parameters.Get ("name", name);
    GS::Array<GS::UniString> folderPath;
    parameters.Get ("folderPath", folderPath);
    bool tooLong = name.GetLength () >= API_UniLongNameLen - 1;
    for (const GS::UniString& folder : folderPath) {
        tooLong = tooLong || folder.GetLength () >= API_UniLongNameLen - 1;
    }
    if (tooLong) {
        return CreateErrorResponse (APIERR_BADPARS, "Names must be shorter than 255 characters.");
    }

    API_3DProjectionInfo info {};
    GSErrCode err = ACAPI_View_Get3DProjectionSets (&info);
    if (err != NoError) {
        return CreateErrorResponse (err, "Failed to read the 3D projection.");
    }

    // The Project Map's generic 3D item follows the current 3D projection; its clone
    // in the View Map keeps that camera.
    API_NavigatorItem search {};
    search.mapId = API_ProjectMap;
    search.itemType = info.isPersp ? API_PerspectiveNavItem : API_AxonometryNavItem;
    GS::Array<API_NavigatorItem> sources;
    err = ACAPI_Navigator_SearchNavigatorItem (&search, &sources);
    if (err != NoError || sources.IsEmpty ()) {
        return CreateErrorResponse (err != NoError ? err : APIERR_GENERAL, "The Project Map has no 3D item to clone.");
    }

    API_NavigatorSet viewMap {};
    viewMap.mapId = API_PublicViewMap;
    err = ACAPI_Navigator_GetNavigatorSet (&viewMap);
    if (err != NoError) {
        return CreateErrorResponse (err, "Failed to read the View Map.");
    }
    API_Guid parentGuid = viewMap.rootGuid;
    bool first = true;
    for (const GS::UniString& folder : folderPath) {
        if (first) {
            first = false;
            if (FindFolderAnywhere (viewMap.rootGuid, folder, parentGuid)) {
                continue;
            }
        }
        err = FindOrCreateFolder (parentGuid, folder, parentGuid);
        if (err != NoError) {
            return CreateErrorResponse (err, "Failed to find or create the View Map folder " + folder + ".");
        }
    }

    API_Guid createdGuid = APINULLGuid;
    err = ACAPI_Navigator_CloneProjectMapItemToViewMap (&sources[0].guid, &parentGuid, &createdGuid);
    if (err != NoError) {
        return CreateErrorResponse (err, "Failed to save the 3D view in the View Map.");
    }

    API_NavigatorItem created {};
    created.mapId = API_PublicViewMap;
    err = ACAPI_Navigator_GetNavigatorItem (&createdGuid, &created);
    if (err == NoError) {
        SetItemName (created, name);
        err = ACAPI_Navigator_ChangeNavigatorItem (&created);
    }
    if (err != NoError) {
        return CreateErrorResponse (err, "Saved the 3D view but failed to name it.");
    }

    GS::ObjectState response ("viewGuid", APIGuidToString (createdGuid), "name", name, "isPerspective", info.isPersp);
    if (!folderPath.IsEmpty ()) {
        response.Add ("folderGuid", APIGuidToString (parentGuid));
    }
    return response;
}

// pa..pd are passed raw. Live read (AC30, 22/10/2026): a horizontal cut at height h is
// cutStatus 8, pc 1, pd h (metres); the other combinations are not mapped yet.
static GS::ObjectState CutPlanesToObjectState (const API_3DCutPlanesInfo& info)
{
    GS::ObjectState os ("enabled", info.isCutPlanes);
    const auto& planes = os.AddList<GS::ObjectState> ("planes");
    for (short i = 0; i < info.nShapes && info.shapes != nullptr; ++i) {
        const API_3DCutShapeType& shape = (*info.shapes)[i];
        planes (GS::ObjectState ("cutStatus", shape.cutStatus, "cutPen", shape.cutPen,
            "pa", shape.pa, "pb", shape.pb, "pc", shape.pc, "pd", shape.pd));
    }
    return os;
}

GS::String Get3DCutPlanesCommand::GetName () const
{
    return "Get3DCutPlanes";
}

GS::Optional<GS::UniString> Get3DCutPlanesCommand::GetInputParametersSchema () const
{
    return R"({
        "type": "object",
        "properties": {},
        "additionalProperties": false
    })";
}

GS::ObjectState Get3DCutPlanesCommand::Execute (const GS::ObjectState& /*parameters*/, GS::ProcessControl& /*processControl*/) const
{
    API_3DCutPlanesInfo info {};
    const GSErrCode err = ACAPI_View_Get3DCuttingPlanes (&info);
    if (err != NoError) {
        return CreateErrorResponse (err, "Failed to read the 3D cutting planes.");
    }
    GS::ObjectState response = CutPlanesToObjectState (info);
    if (info.shapes != nullptr) {
        BMKillHandle (reinterpret_cast<GSHandle*> (&info.shapes));
    }
    return response;
}

GS::String Set3DCutPlanesCommand::GetName () const
{
    return "Set3DCutPlanes";
}

GS::Optional<GS::UniString> Set3DCutPlanesCommand::GetInputParametersSchema () const
{
    return R"({
        "type": "object",
        "properties": {
            "enabled": {"type": "boolean"},
            "planes": {
                "type": "array",
                "maxItems": 20,
                "description": "Planes in the shape Get3DCutPlanes returns; left out, the current planes stay.",
                "items": {
                    "type": "object",
                    "properties": {
                        "cutStatus": {"type": "integer"},
                        "cutPen": {"type": "integer"},
                        "pa": {"type": "number"},
                        "pb": {"type": "number"},
                        "pc": {"type": "number"},
                        "pd": {"type": "number"}
                    },
                    "additionalProperties": false,
                    "required": ["cutStatus", "pa", "pb", "pc", "pd"]
                }
            }
        },
        "additionalProperties": false,
        "required": ["enabled"]
    })";
}

GS::ObjectState Set3DCutPlanesCommand::Execute (const GS::ObjectState& parameters, GS::ProcessControl& /*processControl*/) const
{
    API_3DCutPlanesInfo info {};
    GSErrCode err = ACAPI_View_Get3DCuttingPlanes (&info);
    if (err != NoError) {
        return CreateErrorResponse (err, "Failed to read the 3D cutting planes.");
    }
    parameters.Get ("enabled", info.isCutPlanes);

    GS::Array<GS::ObjectState> planes;
    if (parameters.Get ("planes", planes)) {
        // A plane without cutPen keeps the pen of the plane it replaces.
        GS::Array<short> oldPens;
        for (short i = 0; i < info.nShapes && info.shapes != nullptr; ++i) {
            oldPens.Push ((*info.shapes)[i].cutPen);
        }
        if (info.shapes != nullptr) {
            BMKillHandle (reinterpret_cast<GSHandle*> (&info.shapes));
        }
        info.nShapes = static_cast<short> (planes.GetSize ());
        if (info.nShapes > 0) {
            info.shapes = reinterpret_cast<API_3DCutShapeType**> (BMAllocateHandle (info.nShapes * sizeof (API_3DCutShapeType), ALLOCATE_CLEAR, 0));
            if (info.shapes == nullptr) {
                return CreateErrorResponse (APIERR_MEMFULL, "Failed to allocate the cutting planes.");
            }
            for (short i = 0; i < info.nShapes; ++i) {
                API_3DCutShapeType& shape = (*info.shapes)[i];
                const GS::ObjectState& plane = planes[i];
                Int32 value = 0;
                plane.Get ("cutStatus", value);
                shape.cutStatus = static_cast<short> (value);
                value = i < static_cast<short> (oldPens.GetSize ()) ? oldPens[i] : 0;
                plane.Get ("cutPen", value);
                shape.cutPen = static_cast<short> (value);
                plane.Get ("pa", shape.pa);
                plane.Get ("pb", shape.pb);
                plane.Get ("pc", shape.pc);
                plane.Get ("pd", shape.pd);
            }
        }
    }

    err = ACAPI_View_Change3DCuttingPlanes (&info);
    if (info.shapes != nullptr) {
        BMKillHandle (reinterpret_cast<GSHandle*> (&info.shapes));
    }
    if (err != NoError) {
        return CreateErrorResponse (err, "Failed to change the 3D cutting planes.");
    }

    API_3DCutPlanesInfo after {};
    err = ACAPI_View_Get3DCuttingPlanes (&after);
    if (err != NoError) {
        return CreateErrorResponse (err, "Changed the 3D cutting planes but failed to read them back.");
    }
    GS::ObjectState response = CutPlanesToObjectState (after);
    if (after.shapes != nullptr) {
        BMKillHandle (reinterpret_cast<GSHandle*> (&after.shapes));
    }
    return response;
}

GS::String Show3DAllCommand::GetName () const
{
    return "Show3DAll";
}

GS::Optional<GS::UniString> Show3DAllCommand::GetInputParametersSchema () const
{
    return R"({
        "type": "object",
        "properties": {
            "showAll": {"type": "boolean", "description": "Show All in 3D, which clears the 3D element filter. Default true."},
            "fitInWindow": {"type": "boolean", "description": "Fit in Window on the 3D window; it may move a perspective camera. Default false."}
        },
        "additionalProperties": false
    })";
}

GS::ObjectState Show3DAllCommand::Execute (const GS::ObjectState& parameters, GS::ProcessControl& /*processControl*/) const
{
    bool showAll = true;
    bool fitInWindow = false;
    parameters.Get ("showAll", showAll);
    parameters.Get ("fitInWindow", fitInWindow);
    if (showAll) {
        const GSErrCode err = ACAPI_View_ShowAllIn3D ();
        if (err != NoError) {
            return CreateErrorResponse (err, "Failed to show all in 3D.");
        }
    }
    if (fitInWindow) {
        const GSErrCode err = ACAPI_View_Zoom ();
        if (err != NoError) {
            return CreateErrorResponse (err, "Failed to fit the 3D window; it must be the front window.");
        }
    }
    return GS::ObjectState ("showAll", showAll, "fitInWindow", fitInWindow);
}

#ifdef ServerMainVers_3000
GS::String Get3DWindowImageCommand::GetName () const
{
    return "Get3DWindowImage";
}

GS::Optional<GS::UniString> Get3DWindowImageCommand::GetInputParametersSchema () const
{
    return R"({
        "type": "object",
        "properties": {
            "format": {"type": "string", "enum": ["png", "jpg"], "description": "Default png."}
        },
        "additionalProperties": false
    })";
}

GS::ObjectState Get3DWindowImageCommand::Execute (const GS::ObjectState& parameters, GS::ProcessControl& /*processControl*/) const
{
    NewDisplay::NativeImage::Encoding encoding = NewDisplay::NativeImage::Encoding::PNG;
    GS::UniString format;
    if (parameters.Get ("format", format) && format == "jpg") {
        encoding = NewDisplay::NativeImage::Encoding::JPEG;
    }

    NewDisplay::NativeImage image;
    const GSErrCode err = ACAPI_View_GetCurrentImage (image, API_ImageSource::From3DWindow);
    if (err != NoError) {
        return CreateErrorResponse (err, "Failed to get the 3D window image; show the 3D window first.");
    }

    GS::MemoryOChannel32 channel (GS::MemoryOChannel32::BMAllocation);
    if (!image.Encode (channel, encoding)) {
        return CreateErrorResponse (APIERR_GENERAL, "Failed to encode the 3D window image.");
    }
    auto encoded = Base64Converter::Encode (channel.GetDestination (), channel.GetDataSize ());
    encoded.DeleteAll (GS::UniChar (char ('\n')));

    return GS::ObjectState ("image", encoded);
}
#endif
