#include "CameraCommands.hpp"

#ifdef ServerMainVers_3000
#include "NativeImage.hpp"
#include "MemoryOChannel32.hpp"
#include "Base64Converter.hpp"
#endif

#include <cmath>

// Not tested live yet: the azimuth convention and the parallel projection fields below
// follow the API reference only and must be checked in Archicad (addon/CAMERA.md).

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
        os.Add ("viewCone", p.viewCone);
        os.Add ("rollAngle", p.rollAngle);
        os.Add ("distance", p.distance);
        os.Add ("azimuth", p.azimuth);
        os.Add ("twoPointPerspective", p.isTwoPointPersp);
    } else {
        const API_AxonoPars& a = info.u.axono;
        os.Add ("azimuth", a.azimuth);
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
                "description": "Perspective camera, in metres; the view cone in radians.",
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
                "description": "Parallel projection: azimuth in radians and Archicad's projection mode number.",
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
        info.isPersp = true;
        API_PerspPars& p = info.u.persp;
        p.pos = camera;
        p.target = target;
        p.cameraZ = cameraZ;
        p.targetZ = targetZ;
        p.distance = distance;
        p.azimuth = std::atan2 (camera.y - target.y, camera.x - target.x);
        p.rollAngle = 0.0;
        perspective->Get ("viewCone", p.viewCone);
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
        parallel->Get ("azimuth", a.azimuth);
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
