#include "ObjectReplacementCommands.hpp"
#include "OnExit.hpp"
#include <cmath>
#include <string>

namespace {
// Changes after an add-on/application restart, even when the port is reused.
const API_Guid bootId = APIGuidFromString (GS::Guid (GS::Guid::GenerateGuid).ToUniString ().ToCStr ().Get ());

API_AddParType* Numeric (API_AddParType** parameters, const char* name)
{
    if (parameters == nullptr) return nullptr;
    const GSSize count = BMGetHandleSize ((GSHandle) parameters) / sizeof (API_AddParType);
    for (GSIndex i = 0; i < count; ++i) {
        API_AddParType& p = (*parameters)[i];
        if (CHEqualCStrings (p.name, name) && p.typeMod != API_ParArray &&
            (p.typeID == APIParT_Length || p.typeID == APIParT_RealNum)) return &p;
    }
    return nullptr;
}

GS::ObjectState Parameters (API_AddParType** parameters)
{
    GS::ObjectState result;
    const auto& list = result.AddList<GS::ObjectState> ("items");
    if (parameters == nullptr) return result;
    const GSSize count = BMGetHandleSize ((GSHandle) parameters) / sizeof (API_AddParType);
    for (GSIndex i = 0; i < count; ++i) {
        const API_AddParType& p = (*parameters)[i];
        GS::ObjectState row ("name", GS::UniString (p.name), "type", (Int32) p.typeID);
        if (p.typeMod == API_ParArray) {
            row.Add ("array", true);
            row.Add ("dimension1", (Int32) p.dim1);
            row.Add ("dimension2", (Int32) p.dim2);
        } else if (p.typeID == APIParT_CString || p.typeID == APIParT_Title) {
            row.Add ("value", GS::UniString (p.value.uStr));
        } else if (p.typeID != APIParT_Separator && p.typeID != APIParT_Dictionary) {
            row.Add ("value", p.value.real);
        }
        list (row);
    }
    return result;
}

GSErrCode Library (Int32 index, GS::ObjectState& description, API_ElementMemo& memo)
{
    API_LibPart part = {};
    part.index = index;
    GSErrCode error = ACAPI_LibraryPart_Get (&part);
    delete part.location;
    if (error != NoError) return error;
    if (part.typeID != APILib_ObjectID) return APIERR_BADID;
    double a = 0, b = 0;
    Int32 count = 0;
    error = ACAPI_LibraryPart_GetParams (index, &a, &b, &count, &memo.params);
    if (error != NoError) return error;
    const auto* z = Numeric (memo.params, "ZZYZX");
    description = GS::ObjectState ("index", index, "unid", GS::UniString (part.ownUnID),
        "name", GS::UniString (part.docu_UName), "a", a, "b", b,
        "height", z == nullptr ? 0.0 : z->value.real, "parameters", Parameters (memo.params));
    return NoError;
}

GSErrCode FindLibrary (const GS::UniString& unid, Int32& found)
{
    Int32 count = 0;
    GSErrCode error = ACAPI_LibraryPart_GetNum (&count);
    if (error != NoError) return error;
    found = 0;
    for (Int32 i = 1; i <= count; ++i) {
        API_LibPart part = {};
        part.index = i;
        const GSErrCode e = ACAPI_LibraryPart_Get (&part);
        delete part.location;
        if (e == NoError && GS::UniString (part.ownUnID) == unid) {
            if (found != 0) return APIERR_BADPARS; // Ambiguous, never select the first.
            found = i;
        }
    }
    return found == 0 ? APIERR_BADID : NoError;
}

GSErrCode Describe (const API_Guid& guid, GS::ObjectState& result)
{
    API_Element element = {};
    element.header.guid = guid;
    GSErrCode error = ACAPI_Element_Get (&element);
    if (error != NoError) return error;
    if (element.header.type != API_ElemType (API_ObjectID) ||
        element.header.hotlinkGuid != APINULLGuid || element.object.owner != APINULLGuid)
        return APIERR_BADID;
    API_ElementMemo memo = {}, libraryMemo = {};
    const GS::OnExit guard ([&] () { ACAPI_DisposeElemMemoHdls (&memo); ACAPI_DisposeElemMemoHdls (&libraryMemo); });
    error = ACAPI_Element_GetMemo (guid, &memo, APIMemoMask_AddPars);
    if (error != NoError) return error;
    GS::ObjectState library;
    error = Library (element.object.libInd, library, libraryMemo);
    if (error != NoError) return error;
    double a = 0, b = 0;
    library.Get ("a", a); library.Get ("b", b);
    const auto* z = Numeric (memo.params, "ZZYZX");
    result = GS::ObjectState ("guid", APIGuidToString (guid),
        "stamp", GS::UniString (std::to_string (element.header.modiStamp).c_str ()),
        "library", library, "floorIndex", (Int32) element.header.floorInd,
        "layerIndex", element.header.layer.ToInt32_Deprecated (),
        "x", element.object.pos.x, "y", element.object.pos.y, "level", element.object.level,
        "angle", element.object.angle, "reflected", element.object.reflected,
        "xRatio", element.object.xRatio, "yRatio", element.object.yRatio,
        "useXYFixSize", element.object.useXYFixSize,
        "a", element.object.xRatio * (element.object.useXYFixSize ? 1.0 : a),
        "b", element.object.yRatio * (element.object.useXYFixSize ? 1.0 : b),
        "height", z == nullptr ? 0.0 : z->value.real,
        "fixPoint", (Int32) element.object.fixPoint,
        "offsetX", element.object.offset.x, "offsetY", element.object.offset.y,
        "parameters", Parameters (memo.params));
    API_Guid group = APINULLGuid;
    const GSErrCode groupError = ACAPI_Grouping_GetGroup (guid, &group);
    result.Add ("groupGuid", APIGuidToString (group));
    result.Add ("groupReadCode", (Int32) groupError);
    GS::Array<GS::Pair<API_Guid, API_Guid>> classifications;
    error = ACAPI_Element_GetClassificationItems (guid, classifications);
    if (error != NoError) return error;
    const auto& classificationRows = result.AddList<GS::ObjectState> ("classifications");
    for (const auto& pair : classifications) {
        classificationRows (GS::ObjectState ("system", APIGuidToString (pair.first), "item", APIGuidToString (pair.second)));
    }
    return NoError;
}
}

GS::String GetObjectReplacementDataCommand::GetName () const { return "GetObjectReplacementData"; }
GS::Optional<GS::UniString> GetObjectReplacementDataCommand::GetInputParametersSchema () const
{
    return R"({"type":"object","properties":{"guids":{"type":"array","maxItems":50,"items":{"type":"string"}},"targetUnid":{"type":"string"}},"required":["guids","targetUnid"],"additionalProperties":false})";
}
GS::ObjectState GetObjectReplacementDataCommand::Execute (const GS::ObjectState& input, GS::ProcessControl&) const
{
    GS::UniString unid;
    input.Get ("targetUnid", unid);
    Int32 index = 0;
    GSErrCode error = FindLibrary (unid, index);
    if (error != NoError) return CreateErrorResponse (error, "Target library is missing or ambiguous; use its exact full unique ID.");
    API_ElementMemo memo = {};
    const GS::OnExit guard ([&] () { ACAPI_DisposeElemMemoHdls (&memo); });
    GS::ObjectState target;
    error = Library (index, target, memo);
    if (error != NoError) return CreateErrorResponse (error, "Target must be an Object library part with readable parameters.");
    GS::ObjectState result ("sessionId", APIGuidToString (bootId), "target", target);
    const auto& rows = result.AddList<GS::ObjectState> ("objects");
    GS::Array<GS::UniString> guids;
    input.Get ("guids", guids);
    for (const auto& guid : guids) {
        GS::ObjectState row;
        error = Describe (APIGuidFromString (guid.ToCStr ().Get ()), row);
        rows (error == NoError ? row : CreateErrorResponse (error, "Not an editable standalone Object."));
    }
    return result;
}

GS::String ReplaceObjectLibrariesCommand::GetName () const { return "ReplaceObjectLibraries"; }
GS::Optional<GS::UniString> ReplaceObjectLibrariesCommand::GetInputParametersSchema () const
{
    return R"({"type":"object","properties":{"sessionId":{"type":"string"},"targetUnid":{"type":"string"},"targetIndex":{"type":"integer"},"objects":{"type":"array","minItems":1,"maxItems":50,"items":{"type":"object","properties":{"guid":{"type":"string"},"stamp":{"type":"string"},"x":{"type":"number"},"y":{"type":"number"},"level":{"type":"number"},"a":{"type":"number","exclusiveMinimum":0},"b":{"type":"number","exclusiveMinimum":0},"height":{"type":"number","exclusiveMinimum":0}},"required":["guid","stamp","x","y","level","a","b","height"],"additionalProperties":false}}},"required":["sessionId","targetUnid","targetIndex","objects"],"additionalProperties":false})";
}
GS::ObjectState ReplaceObjectLibrariesCommand::Execute (const GS::ObjectState& input, GS::ProcessControl&) const
{
    GS::UniString session, unid;
    Int32 index = 0, wantedIndex = 0;
    input.Get ("sessionId", session); input.Get ("targetUnid", unid); input.Get ("targetIndex", wantedIndex);
    if (session != APIGuidToString (bootId)) return CreateErrorResponse (APIERR_BADPARS, "Add-on session changed. Preview again.");
    GSErrCode error = FindLibrary (unid, index);
    if (error != NoError || index != wantedIndex) return CreateErrorResponse (APIERR_BADID, "Target library identity changed.");
    GS::Array<GS::ObjectState> rows;
    input.Get ("objects", rows);
    // Preflight the complete batch before the first mutation, then check stamps again inside Undo.
    for (const auto& row : rows) {
        GS::UniString guid, stamp, actual;
        row.Get ("guid", guid); row.Get ("stamp", stamp);
        GS::ObjectState current;
        error = Describe (APIGuidFromString (guid.ToCStr ().Get ()), current);
        current.Get ("stamp", actual);
        if (error != NoError || stamp != actual) return CreateErrorResponse (APIERR_BADPARS, "Source object changed since preview.");
    }
    error = ACAPI_CallUndoableCommand ("Replace object libraries", [&] () -> GSErrCode {
        for (const auto& row : rows) {
            GS::UniString guid, stamp;
            row.Get ("guid", guid); row.Get ("stamp", stamp);
            API_Element element = {}, mask = {};
            element.header.guid = APIGuidFromString (guid.ToCStr ().Get ());
            GSErrCode e = ACAPI_Element_Get (&element);
            if (e != NoError) return e;
            if (stamp != GS::UniString (std::to_string (element.header.modiStamp).c_str ())) return APIERR_BADPARS;
            API_ElementMemo memo = {};
            const GS::OnExit guard ([&] () { ACAPI_DisposeElemMemoHdls (&memo); });
            GS::ObjectState target;
            e = Library (index, target, memo);
            if (e != NoError) return e;
            double a = 0, b = 0, height = 0;
            row.Get ("a", a); row.Get ("b", b); row.Get ("height", height);
            if (!std::isfinite (a) || !std::isfinite (b) || !std::isfinite (height) || a <= 0 || b <= 0 || height <= 0) return APIERR_BADPARS;
            auto* pa = Numeric (memo.params, "A"); auto* pb = Numeric (memo.params, "B"); auto* pz = Numeric (memo.params, "ZZYZX");
            if (pa == nullptr || pb == nullptr || pz == nullptr) return APIERR_BADPARS;
            pa->value.real = a; pb->value.real = b; pz->value.real = height;
            element.object.libInd = index;
            element.object.useXYFixSize = true;
            element.object.xRatio = a; element.object.yRatio = b;
            element.object.fixPoint = -1; element.object.offset = {};
            row.Get ("x", element.object.pos.x); row.Get ("y", element.object.pos.y); row.Get ("level", element.object.level);
            ACAPI_ELEMENT_MASK_CLEAR (mask);
            ACAPI_ELEMENT_MASK_SET (mask, API_ObjectType, libInd);
            ACAPI_ELEMENT_MASK_SET (mask, API_ObjectType, useXYFixSize);
            ACAPI_ELEMENT_MASK_SET (mask, API_ObjectType, xRatio);
            ACAPI_ELEMENT_MASK_SET (mask, API_ObjectType, yRatio);
            ACAPI_ELEMENT_MASK_SET (mask, API_ObjectType, pos);
            ACAPI_ELEMENT_MASK_SET (mask, API_ObjectType, level);
            ACAPI_ELEMENT_MASK_SET (mask, API_ObjectType, fixPoint);
            ACAPI_ELEMENT_MASK_SET (mask, API_ObjectType, offset);
            e = ACAPI_Element_Change (&element, &mask, &memo, APIMemoMask_AddPars, true);
            if (e != NoError) return e;
        }
        return NoError;
    });
    if (error != NoError) return CreateErrorResponse (error, "Object replacement batch failed; Undo transaction rolled back.");
    GS::ObjectState result;
    const auto& after = result.AddList<GS::ObjectState> ("objects");
    for (const auto& row : rows) {
        GS::UniString guid; row.Get ("guid", guid);
        GS::ObjectState current;
        error = Describe (APIGuidFromString (guid.ToCStr ().Get ()), current);
        after (error == NoError ? current : CreateErrorResponse (error, "Replacement readback failed."));
    }
    return result;
}
