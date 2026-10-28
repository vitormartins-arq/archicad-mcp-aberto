#include "CameraPathCommands.hpp"
#include "CameraAngleConversion.hpp"
#include "ProjectSaveCommands.hpp"
#include "OnExit.hpp"
#include "ObjectStateJSONConversion.hpp"
#include "GSGuid.hpp"
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstring>
#include <map>
#include <memory>
#include <stdexcept>
#include <string>
#include <vector>

namespace {
using Clock = std::chrono::steady_clock;
constexpr const char* SourcePrefix = "MCP_CAMERA_SOURCE_V1:";
void Check (GSErrCode err) { if (err != NoError) throw std::runtime_error (std::to_string (err)); }
std::string Utf8 (const GS::UniString& value) { return value.ToCStr (CC_UTF8).Get (); }
std::string Json (const GS::ObjectState& value)
{
    GS::UniString text;
    Check (JSON::CreateFromObjectState (value, text, false));
    return Utf8 (text);
}
GS::UniString Hex (const void* value, size_t size)
{
    const auto* bytes = static_cast<const unsigned char*> (value);
    const char* digits = "0123456789abcdef";
    std::string out;
    out.reserve (size * 2);
    for (size_t i = 0; i < size; ++i) { out += digits[bytes[i] >> 4]; out += digits[bytes[i] & 15]; }
    return GS::UniString (out.c_str ());
}
GS::ObjectState ProjectContext (GS::ProcessControl& process)
{
    auto context = GetProjectSaveContextCommand ().Execute (GS::ObjectState {}, process);
    if (context.Contains ("error")) throw std::runtime_error ("Cannot identify the project.");
    bool teamwork = true, untitled = true;
    context.Get ("teamwork", teamwork); context.Get ("untitled", untitled);
    if (teamwork || untitled) throw std::runtime_error ("A saved standalone PLN is required for automatic backup.");
    return context;
}
GS::ObjectState Perspective (const API_PerspPars& p)
{
    // Raw values: projection settings use degrees; camera elements use radians.
    return GS::ObjectState ("x", p.pos.x, "y", p.pos.y, "z", p.cameraZ,
        "targetX", p.target.x, "targetY", p.target.y, "targetZ", p.targetZ,
        "viewConeNative", p.viewCone, "rollNative", p.rollAngle, "azimuthNative", p.azimuth,
        "distance", p.distance, "twoPoint", p.isTwoPointPersp,
        "sunSettings", Hex (&p.sunAngSets, sizeof p.sunAngSets));
}
bool SamePerspective (const API_PerspPars& a, const API_PerspPars& b)
{
    auto closeValue = [] (double x, double y) { return std::isfinite (x) && std::isfinite (y) && std::abs (x-y) <= 1e-7; };
    return closeValue (a.pos.x,b.pos.x) && closeValue (a.pos.y,b.pos.y) && closeValue (a.cameraZ,b.cameraZ) &&
        closeValue (a.target.x,b.target.x) && closeValue (a.target.y,b.target.y) && closeValue (a.targetZ,b.targetZ) &&
        closeValue (a.viewCone,b.viewCone) && closeValue (a.rollAngle,b.rollAngle) && closeValue (a.azimuth,b.azimuth) &&
        closeValue (a.distance,b.distance) && a.isTwoPointPersp == b.isTwoPointPersp;
}
GS::ObjectState Cutting (const API_3DCutPlanesInfo& cut)
{
    GS::ObjectState out ("enabled", cut.isCutPlanes, "custom", cut.useCustom,
        "pen", cut.customPen, "material", cut.customMater.ToInt32_Deprecated ());
    const auto& list = out.AddList<GS::ObjectState> ("planes");
    if (cut.nShapes < 0 || (cut.nShapes > 0 && cut.shapes == nullptr))
        throw std::runtime_error ("Incomplete cutting planes.");
    for (short i = 0; i < cut.nShapes; ++i) {
        const auto& p = (*cut.shapes)[i];
        list (GS::ObjectState ("status", p.cutStatus, "pen", p.cutPen,
            "material", p.cutMater.ToInt32_Deprecated (), "a", p.pa, "b", p.pb, "c", p.pc, "d", p.pd));
    }
    return out;
}
GS::ObjectState Filters (const API_3DFilterAndCutSettings& f)
{
    GS::ObjectState out ("allStories", f.allStories, "firstStory", f.firstStory3D,
        "lastStory", f.lastStory3D, "trim", f.trimToStoryRange, "mode", static_cast<Int32> (f.filterMode),
        "marqueeMode", static_cast<Int32> (f.marqueeFilter.elemsInMarquee),
        "marqueeStory", f.marqueeFilter.marqueeStory,
        "marqueeType", static_cast<Int32> (f.marqueeFilter.marqueeType));
    const auto& list = out.AddList<GS::ObjectState> ("elementTypes");
    for (const auto& pair : f.elemTypeFilter)
        list (GS::ObjectState ("type", static_cast<Int32> (pair.first), "visible", pair.second));
    return out;
}
GS::ObjectState EffectiveConfiguration ()
{
    API_3DCutPlanesInfo cut {};
    const GS::OnExit freeCut ([&] { if (cut.shapes) BMKillHandle (reinterpret_cast<GSHandle*> (&cut.shapes)); });
    Check (ACAPI_View_Get3DCuttingPlanes (&cut));
    API_3DFilterAndCutSettings filter {};
    Check (ACAPI_View_Get3DImageSets (&filter));
    API_ViewOptions options {};
    const GS::OnExit freeOptions ([&] { ACAPI_FreeGDLModelViewOptionsPtr (&options.modelViewOpt.gdlOptions); });
    Check (ACAPI_Navigator_GetViewOptions (&options));
    auto scalarOptions = options.modelViewOpt;
    scalarOptions.gdlOptions = nullptr;
    GS::ObjectState out ("cutting", Cutting (cut), "filters", Filters (filter),
        "modelViewOptionsNative", Hex (&scalarOptions, sizeof scalarOptions));
    const auto& gdls = out.AddList<GS::ObjectState> ("gdlModelViewOptions");
    if (options.modelViewOpt.gdlOptions != nullptr) {
        const auto count = BMGetPtrSize (reinterpret_cast<GSPtr> (options.modelViewOpt.gdlOptions)) / sizeof (API_GDLModelViewOptions);
        for (size_t i = 0; i < count; ++i) {
            const auto& gdl = options.modelViewOpt.gdlOptions[i];
            gdls (GS::ObjectState ("guid", APIGuidToString (gdl.guid),
                "checksum", GS::UniString (gdl.checkSum, CC_UTF8)));
        }
    }
    GS::Array<API_Attribute> layers;
    Check (ACAPI_Attribute_GetAttributesByType (API_LayerID, layers));
    std::vector<std::pair<Int32,Int32>> sorted;
    for (const auto& layer : layers)
        sorted.emplace_back (layer.header.index.ToInt32_Deprecated (), static_cast<Int32> (layer.header.flags));
    std::sort (sorted.begin (), sorted.end ());
    const auto& list = out.AddList<GS::ObjectState> ("effectiveLayers");
    for (const auto& layer : sorted) list (GS::ObjectState ("index", layer.first, "flags", layer.second));
    return out;
}
struct ViewState {
    API_WindowInfo window {};
    API_3DProjectionInfo projection {};
    API_3DCutPlanesInfo cut {};
    API_3DFilterAndCutSettings filter {};
    API_SelectionInfo selection {};
    GS::Array<API_Neig> neigs;
    bool stored = false;
    ViewState ()
    {
      try {
        Check (ACAPI_Window_GetCurrentWindow (&window));
        Check (ACAPI_View_Get3DProjectionSets (&projection));
        Check (ACAPI_View_Get3DImageSets (&filter));
        Check (ACAPI_View_Get3DCuttingPlanes (&cut));
        const auto err = ACAPI_Selection_Get (&selection, &neigs, false);
        if (err != NoError && err != APIERR_NOSEL) throw std::runtime_error ("Cannot preserve selection.");
        Check (ACAPI_View_StoreViewSettings (true)); stored = true;
    }
    catch (...) {
        if (cut.shapes) BMKillHandle (reinterpret_cast<GSHandle*> (&cut.shapes));
        if (selection.marquee.coords) BMKillHandle (reinterpret_cast<GSHandle*> (&selection.marquee.coords));
        throw;
      }
    }
    GSErrCode Restore ()
    {
        if (!stored) return NoError;
        GSErrCode err = ACAPI_Window_ChangeWindow (&window);
        err |= ACAPI_View_StoreViewSettings (false);
        err |= ACAPI_View_Change3DProjectionSets (&projection);
        err |= ACAPI_View_Change3DCuttingPlanes (&cut);
        err |= ACAPI_View_Change3DImageSets (&filter);
        err |= ACAPI_Selection_DeselectAll ();
        if (!neigs.IsEmpty ()) err |= ACAPI_Selection_Select (neigs, true);
        if (window.typeID == APIWind_FloorPlanID || window.typeID == APIWind_SectionID)
            err |= ACAPI_Selection_SetMarquee (&selection);
        API_WindowInfo after {};
        err |= ACAPI_Window_GetCurrentWindow (&after);
        if (after.typeID != window.typeID || after.databaseUnId.elemSetId != window.databaseUnId.elemSetId)
            err = APIERR_GENERAL;
        stored = false;
        return err;
    }
    ~ViewState ()
    {
        if (stored) Restore ();
        if (cut.shapes) BMKillHandle (reinterpret_cast<GSHandle*> (&cut.shapes));
        if (selection.marquee.coords) BMKillHandle (reinterpret_cast<GSHandle*> (&selection.marquee.coords));
    }
};
struct SourceView {
    API_Guid guid {};
    GS::UniString name;
    API_3DProjectionInfo projection {};
    std::string representation;
    GS::ObjectState Describe () const
    {
        GS::ObjectState out ("sourceViewGuid", APIGuidToString (guid), "name", name,
            "isPerspective", projection.isPersp, "representationJSON", GS::UniString (representation.c_str (), CC_UTF8));
        if (projection.isPersp) out.Add ("projection", Perspective (projection.u.persp));
        return out;
    }
};
std::vector<SourceView> Capture (const GS::Array<GS::UniString>& ids)
{
    ViewState initial;
    std::vector<SourceView> result;
    try {
        for (const auto& id : ids) {
            SourceView view;
            view.guid = APIGuidFromString (id.ToCStr ().Get ());
            API_NavigatorItem item {};
            Check (ACAPI_Navigator_GetNavigatorItem (&view.guid, &item));
            if (item.itemType != API_PerspectiveNavItem && item.itemType != API_AxonometryNavItem)
                throw std::runtime_error ("Source must be a saved 3D view, not a 3D document.");
            view.name = GS::UniString (item.uName);
            Check (ACAPI_View_GoToView (id.ToCStr ().Get ()));
            Check (ACAPI_View_Get3DProjectionSets (&view.projection));
            auto config = EffectiveConfiguration ();
            API_NavigatorView settings {};
            const GS::OnExit freeSettings ([&] {
                if (settings.modelViewOpt) ACAPI_FreeGDLModelViewOptionsPtr (&settings.modelViewOpt->gdlOptions);
                delete settings.modelViewOpt; delete settings.layerStats; delete settings.dimPrefs; delete settings.pens;
            });
            Check (ACAPI_Navigator_GetNavigatorView (&item, &settings));
            config.Add ("structure", static_cast<Int32> (settings.structureDisplay));
            config.Add ("renovation", APIGuidToString (settings.renovationFilterGuid));
            config.Add ("override", GS::UniString (settings.overrideCombination));
            config.Add ("style", GS::UniString (settings.d3styleName));
            config.Add ("rendering", GS::UniString (settings.renderingSceneName));
            config.Add ("useRendering", settings.usePhotoRendering);
            view.representation = Json (config);
            result.push_back (std::move (view));
        }
    } catch (...) {
        if (initial.Restore () != NoError) throw std::runtime_error ("Source read failed AND original view restoration needs inspection.");
        throw;
    }
    if (initial.Restore () != NoError) throw std::runtime_error ("Original view restoration failed; no cameras created.");
    return result;
}
std::string SourceOf (API_Element& element)
{
    API_ElementUserData data {};
    const GS::OnExit release ([&] { if (data.dataHdl) BMKillHandle (&data.dataHdl); });
    const auto err = ACAPI_Element_GetUserData (&element.header, &data);
    if (err == APIERR_NOUSERDATA) return "";
    Check (err);
    if (data.dataVersion != 1 || data.dataHdl == nullptr) return "";
    const auto length = BMhGetSize (data.dataHdl);
    if (length < 1 || length > 512) return "";
    const std::string value (*data.dataHdl, static_cast<size_t> (length));
    const std::string prefix (SourcePrefix);
    return value.rfind (prefix, 0) == 0 ? value.substr (prefix.size ()) : "";
}
void SetSource (API_Element& element, const API_Guid& source)
{
    const std::string value = std::string (SourcePrefix) + Utf8 (APIGuidToString (source));
    API_ElementUserData data {};
    data.dataVersion = 1;
    data.platformSign = GS::Act_Platform_Sign;
    data.dataHdl = BMAllocateHandle (static_cast<GS::GSSize> (value.size ()), ALLOCATE_CLEAR, 0);
    if (!data.dataHdl) throw std::runtime_error ("Cannot allocate camera source metadata.");
    const GS::OnExit release ([&] { BMKillHandle (&data.dataHdl); });
    std::memcpy (*data.dataHdl, value.data (), value.size ());
    Check (ACAPI_Element_SetUserData (&element.header, &data));
}
struct Inventory {
    std::vector<API_Element> paths;
    std::vector<API_Element> cameras;
    std::map<std::string,std::string> sources;
    GS::ObjectState Describe () const
    {
        GS::ObjectState out;
        const auto& p = out.AddList<GS::ObjectState> ("paths");
        for (const auto& path : paths) p (GS::ObjectState ("guid", APIGuidToString (path.header.guid),
            "name", GS::UniString (path.camset.name), "active", path.camset.active,
            "firstCamera", APIGuidToString (path.camset.firstCam)));
        const auto& c = out.AddList<GS::ObjectState> ("cameras");
        for (const auto& camera : cameras) {
            const auto& v = camera.camera;
            c (GS::ObjectState ("guid", APIGuidToString (camera.header.guid), "pathGuid", APIGuidToString (v.camSetGuid),
                "previous", APIGuidToString (v.perspCam.prevCam), "next", APIGuidToString (v.perspCam.nextCam),
                "sourceViewGuid", GS::UniString (sources.at (Utf8 (APIGuidToString (camera.header.guid))).c_str ()),
                "projection", Perspective (v.perspCam.persp)));
        }
        return out;
    }
};
Inventory ReadInventory ()
{
    Inventory out;
    for (const API_ElemTypeID type : {API_CamSetID, API_CameraID}) {
        GS::Array<API_Guid> ids;
        Check (ACAPI_Element_GetElemList (type, &ids));
        std::vector<std::string> sorted;
        for (const auto& id : ids) sorted.push_back (Utf8 (APIGuidToString (id)));
        std::sort (sorted.begin (), sorted.end ());
        for (const auto& id : sorted) {
            API_Element element {};
            element.header.guid = APIGuidFromString (id.c_str ());
            Check (ACAPI_Element_Get (&element));
            if (type == API_CamSetID) out.paths.push_back (element);
            else { out.sources[id] = SourceOf (element); out.cameras.push_back (element); }
        }
    }
    return out;
}
struct Prepared {
    GS::UniString name;
    GS::Array<GS::UniString> ids;
    std::vector<SourceView> views;
    GS::ObjectState context;
    std::string inventory;
    std::string model;
    bool sealed = false;
    Clock::time_point expires;
};
std::map<std::string,std::shared_ptr<Prepared>> prepared;

std::string ModelState ()
{
    API_DatabaseInfo original {};
    Check (ACAPI_Database_GetCurrentDatabase (&original));
    API_DatabaseInfo floor {};
    floor.typeID = APIWind_FloorPlanID;
    Check (ACAPI_Database_ChangeCurrentDatabase (&floor));
    const GS::OnExit restore ([&] { ACAPI_Database_ChangeCurrentDatabase (&original); });
    GS::Array<API_Guid> ids;
    Check (ACAPI_Element_GetElemList (API_ZombieElemID, &ids));
    std::map<std::string,std::string> versions;
    for (const auto& id : ids) {
        API_Elem_Head head {};
        head.guid = id;
        Check (ACAPI_Element_GetHeader (&head));
        versions.emplace (Utf8 (APIGuidToString (id)), std::to_string (head.modiStamp));
    }
    GS::ObjectState result;
    const auto& elements = result.AddList<GS::ObjectState> ("elements");
    for (const auto& row : versions)
        elements (GS::ObjectState ("guid", GS::UniString (row.first.c_str ()),
            "stamp", GS::UniString (row.second.c_str ())));
    const auto& attributes = result.AddList<GS::ObjectState> ("attributes");
    for (int i = API_FirstAttributeID; i <= API_LastAttributeID; ++i) {
        GS::Array<API_Attribute> rows;
        Check (ACAPI_Attribute_GetAttributesByType (static_cast<API_AttrTypeID> (i), rows));
        std::map<std::string,GS::ObjectState> sorted;
        for (const auto& row : rows) {
            GS::ObjectState item ("type", i, "index", row.header.index.ToInt32_Deprecated (),
                "guid", APIGuidToString (row.header.guid));
            // Layer visibility is reapplied by GoToView. Compare its content after
            // restoration, rather than its timestamp, which can change internally.
            if (i == API_LayerID) {
                item.Add ("flags", static_cast<Int32> (row.header.flags));
                item.Add ("name", GS::UniString (row.header.name, CC_UTF8));
            } else item.Add ("stamp", GS::UniString (std::to_string (row.header.modiTime).c_str ()));
            sorted.emplace (Utf8 (APIGuidToString (row.header.guid)), item);
        }
        for (const auto& row : sorted) attributes (row.second);
    }
    return Json (result);
}
bool SameContext (const GS::ObjectState& a, const GS::ObjectState& b, bool includeStamp)
{
    for (const char* key : {"sessionId", "projectEpoch", "projectPath", "modificationStamp"}) {
        if (!includeStamp && std::string (key) == "modificationStamp") continue;
        GS::UniString x, y;
        if (!a.Get (key, x) || !b.Get (key, y) || x != y) return false;
    }
    return true;
}
}

GS::String GetCameraPathsCommand::GetName () const { return "GetCameraPaths"; }
GS::Optional<GS::UniString> GetCameraPathsCommand::GetInputParametersSchema () const
{ return GS::UniString (R"({"type":"object","additionalProperties":false})"); }
GS::ObjectState GetCameraPathsCommand::Execute (const GS::ObjectState&, GS::ProcessControl&) const
{
    try {
        auto result = ReadInventory ().Describe ();
        API_ViewOptions options {};
        const GS::OnExit freeOptions ([&] { ACAPI_FreeGDLModelViewOptionsPtr (&options.modelViewOpt.gdlOptions); });
        Check (ACAPI_Navigator_GetViewOptions (&options));
        result.Add ("cameraPathDisplayMode", static_cast<Int32> (options.onScreenViewOpt.camPathViewMode));
        return result;
    } catch (const std::exception& e) { return CreateErrorResponse (APIERR_GENERAL, GS::UniString (e.what ())); }
}

GS::String PrepareCameraPathCommand::GetName () const { return "PrepareCameraPath"; }
GS::Optional<GS::UniString> PrepareCameraPathCommand::GetInputParametersSchema () const
{
    return GS::UniString (R"({"type":"object","properties":{"pathName":{"type":"string","minLength":1,"maxLength":200},"viewGuids":{"type":"array","minItems":1,"maxItems":60,"uniqueItems":true,"items":{"type":"string","minLength":36,"maxLength":38}}},"required":["pathName","viewGuids"],"additionalProperties":false})");
}
GS::ObjectState PrepareCameraPathCommand::Execute (const GS::ObjectState& parameters, GS::ProcessControl& process) const
{
    try {
        ProjectContext (process);
        auto plan = std::make_shared<Prepared> ();
        if (!parameters.Get ("pathName", plan->name) || !parameters.Get ("viewGuids", plan->ids) ||
            plan->ids.IsEmpty () || plan->ids.GetSize () > 60 || plan->name.IsEmpty ())
            throw std::runtime_error ("Invalid path name or view list.");
        plan->model = ModelState ();
        plan->views = Capture (plan->ids);
        plan->context = ProjectContext (process);
        const auto inventory = ReadInventory ();
        plan->inventory = Json (inventory.Describe ());
        plan->expires = Clock::now () + std::chrono::minutes (10);
        for (auto it = prepared.begin (); it != prepared.end ();)
            if (it->second->expires <= Clock::now ()) it = prepared.erase (it); else ++it;
        if (prepared.size () >= 32) throw std::runtime_error ("Too many active native previews.");
        const auto token = Utf8 (GS::Guid (GS::Guid::GenerateGuid).ToUniString ());
        GS::ObjectState result ("pathName", plan->name, "nativeToken", GS::UniString (token.c_str ()),
            "context", plan->context, "stateRestored", true, "inventory", inventory.Describe ());
        const auto& rows = result.AddList<GS::ObjectState> ("views");
        for (const auto& view : plan->views) rows (view.Describe ());
        prepared[token] = plan;
        return result;
    } catch (const std::exception& e) { return CreateErrorResponse (APIERR_GENERAL, GS::UniString (e.what ())); }
}

GS::String SealCameraPathCommand::GetName () const { return "SealCameraPath"; }
GS::Optional<GS::UniString> SealCameraPathCommand::GetInputParametersSchema () const
{
    return GS::UniString (R"({"type":"object","properties":{"nativeToken":{"type":"string"},"context":{"type":"object"}},"required":["nativeToken","context"],"additionalProperties":false})");
}
GS::ObjectState SealCameraPathCommand::Execute (const GS::ObjectState& parameters, GS::ProcessControl& process) const
{
    try {
        GS::UniString token;
        GS::ObjectState expected;
        if (!parameters.Get ("nativeToken", token) || !parameters.Get ("context", expected))
            throw std::runtime_error ("Missing seal context/token.");
        const auto found = prepared.find (Utf8 (token));
        if (found == prepared.end () || found->second->expires <= Clock::now () || found->second->sealed)
            throw std::runtime_error ("Native preview missing, expired or already sealed.");
        const auto current = ProjectContext (process);
        const auto& plan = found->second;
        if (!SameContext (current, expected, true) || !SameContext (current, plan->context, false))
            throw std::runtime_error ("Project or stable context changed before sealing.");
        if (ModelState () != plan->model || Json (ReadInventory ().Describe ()) != plan->inventory)
            throw std::runtime_error ("Model/attributes/cameras changed during view capture.");
        plan->context = current;
        plan->sealed = true;
        return GS::ObjectState ("sealed", true, "context", current);
    } catch (const std::exception& e) { return CreateErrorResponse (APIERR_GENERAL, GS::UniString (e.what ()));
    }
}

GS::String ApplyCameraPathCommand::GetName () const { return "ApplyCameraPath"; }
GS::Optional<GS::UniString> ApplyCameraPathCommand::GetInputParametersSchema () const
{
    return GS::UniString (R"({"type":"object","properties":{"nativeToken":{"type":"string"},"hideInPlan":{"type":"boolean"}},"required":["nativeToken"],"additionalProperties":false})");
}
GS::ObjectState ApplyCameraPathCommand::Execute (const GS::ObjectState& parameters, GS::ProcessControl& process) const
{
    GS::UniString token;
    parameters.Get ("nativeToken", token);
    const auto found = prepared.find (Utf8 (token));
    if (found == prepared.end () || found->second->expires <= Clock::now ())
        return CreateErrorResponse (APIERR_BADPARS, "Native preview missing, expired or consumed.");
    const auto plan = found->second;
    prepared.erase (found); // Consume even when validation or creation fails. Never blindly retry.
    try {
        if (!plan->sealed) throw std::runtime_error ("Native preview must be sealed after view updates settle.");
        if (Json (ProjectContext (process)) != Json (plan->context))
            throw std::runtime_error ("Project/session/stamp changed after preview.");
        auto inventory = ReadInventory ();
        if (Json (inventory.Describe ()) != plan->inventory)
            throw std::runtime_error ("Camera paths changed after preview.");
        if (ModelState () != plan->model) throw std::runtime_error ("Model/attributes changed after preview.");
        const auto currentViews = Capture (plan->ids);
        if (currentViews.size () != plan->views.size ()) throw std::runtime_error ("Source view count changed.");
        std::string representation;
        for (size_t i = 0; i < currentViews.size (); ++i) {
            if (Json (currentViews[i].Describe ()) != Json (plan->views[i].Describe ()))
                throw std::runtime_error ("A source view changed after preview.");
            if (!currentViews[i].projection.isPersp)
                throw std::runtime_error ("Parallel/axonometric views cannot be converted to perspective cameras.");
            if (i == 0) representation = currentViews[i].representation;
            else if (currentViews[i].representation != representation)
                throw std::runtime_error ("Separate camera paths are required for different model representations.");
        }
        if (ModelState () != plan->model) throw std::runtime_error ("Model/attributes changed during final capture.");
        API_Guid pathGuid = APINULLGuid;
        API_Guid tail = APINULLGuid;
        int matchedPaths = 0;
        for (const auto& path : inventory.paths) if (GS::UniString (path.camset.name) == plan->name) {
            pathGuid = path.header.guid; ++matchedPaths;
        }
        if (matchedPaths > 1) throw std::runtime_error ("Ambiguous path name; no cameras changed.");
        std::map<std::string,API_Element> bySource;
        if (pathGuid != APINULLGuid) {
            for (const auto& camera : inventory.cameras) if (camera.camera.camSetGuid == pathGuid) {
                const auto key = inventory.sources.at (Utf8 (APIGuidToString (camera.header.guid)));
                if (key.empty ()) throw std::runtime_error ("Target path contains unmanaged cameras; preserved without changes.");
                if (!bySource.emplace (key, camera).second)
                    throw std::runtime_error ("Duplicate source cameras already exist; preserved without changes.");
                if (camera.camera.perspCam.nextCam == APINULLGuid) {
                    if (tail != APINULLGuid) throw std::runtime_error ("Target path links are ambiguous.");
                    tail = camera.header.guid;
                }
            }
        }
        // Existing managed cameras must be the unchanged prefix of the requested order.
        API_Guid previous = APINULLGuid;
        size_t reused = 0;
        for (const auto& view : currentViews) {
            const auto old = bySource.find (Utf8 (APIGuidToString (view.guid)));
            if (old == bySource.end ()) break;
            if (old->second.camera.perspCam.prevCam != previous ||
                !SamePerspective (old->second.camera.perspCam.persp, CameraPerspective (view.projection.u.persp)))
                throw std::runtime_error ("Existing camera order/projection differs; no duplicates created.");
            previous = old->second.header.guid; ++reused;
        }
        if (reused != bySource.size ())
            throw std::runtime_error ("Requested order is not an extension of the existing path.");
        GS::Array<GS::ObjectState> created;
        GSErrCode transaction = NoError;
        if (reused < currentViews.size ()) {
            transaction = ACAPI_CallUndoableCommand ("Create MCP camera path", [&] () -> GSErrCode {
                try {
                    if (pathGuid == APINULLGuid) {
                        API_Element path {};
                        path.header.type = API_CamSetID;
                        GS::ucsncpy (path.camset.name, plan->name.ToUStr ().Get (), API_UniLongNameLen - 1);
                        path.camset.perspPars.openedPath = true;
                        path.camset.perspPars.pen = 1;
                        path.camset.perspPars.inFrames = 1;
                        path.camset.active = false;
                        Check (ACAPI_Element_Create (&path, nullptr));
                        pathGuid = path.header.guid;
                    }
                    for (size_t i = reused; i < currentViews.size (); ++i) {
                        const auto& view = currentViews[i];
                        API_Element camera {};
                        camera.header.type = API_CameraID;
                        Check (ACAPI_Element_GetDefaults (&camera, nullptr));
                        camera.camera.camSetGuid = pathGuid;
                        camera.camera.perspCam.persp = CameraPerspective (view.projection.u.persp);
                        camera.camera.perspCam.prevCam = tail;
                        camera.camera.perspCam.nextCam = APINULLGuid;
                        camera.camera.perspCam.active = true;
                        API_ElementMemo memo {};
                        memo.elemInfoString = new GS::UniString (view.name);
                        const GS::OnExit freeMemo ([&] { ACAPI_DisposeElemMemoHdls (&memo); });
                        Check (ACAPI_Element_Create (&camera, &memo));
                        SetSource (camera, view.guid);
                        tail = camera.header.guid;
                        created.Push (GS::ObjectState ("guid", APIGuidToString (tail),
                            "sourceViewGuid", APIGuidToString (view.guid), "name", view.name));
                    }
                    return NoError;
                } catch (const std::exception&) { return APIERR_GENERAL; }
            });
        }
        if (transaction != NoError)
            return CreateErrorResponse (transaction, "Camera transaction failed; inspect inventory/receipt before any retry.");
        const auto after = ReadInventory ();
        std::map<std::string,API_Element> actual;
        for (const auto& camera : after.cameras) if (camera.camera.camSetGuid == pathGuid) {
            const auto key = after.sources.at (Utf8 (APIGuidToString (camera.header.guid)));
            if (!actual.emplace (key, camera).second) throw std::runtime_error ("Read-back found duplicate source cameras.");
        }
        if (actual.size () != currentViews.size ()) throw std::runtime_error ("Camera count read-back differs.");
        previous = APINULLGuid;
        for (size_t i = 0; i < currentViews.size (); ++i) {
            const auto key = Utf8 (APIGuidToString (currentViews[i].guid));
            const auto camera = actual.find (key);
            if (camera == actual.end () || camera->second.camera.perspCam.prevCam != previous ||
                !SamePerspective (camera->second.camera.perspCam.persp, CameraPerspective (currentViews[i].projection.u.persp)))
                throw std::runtime_error ("Created camera projection/source/order could not be verified.");
            previous = camera->second.header.guid;
        }
        API_Guid expectedNext = APINULLGuid;
        for (auto view = currentViews.rbegin (); view != currentViews.rend (); ++view) {
            const auto& camera = actual.at (Utf8 (APIGuidToString (view->guid)));
            if (camera.camera.perspCam.nextCam != expectedNext)
                throw std::runtime_error ("Camera forward-link read-back differs.");
            expectedNext = camera.header.guid;
        }
        const auto actualPath = std::find_if (after.paths.begin (), after.paths.end (),
            [&] (const auto& path) { return path.header.guid == pathGuid; });
        if (actualPath == after.paths.end () || actualPath->camset.firstCam != expectedNext)
            throw std::runtime_error ("Camera path first-camera read-back differs.");
        bool hide = true;
        parameters.Get ("hideInPlan", hide);
        GSErrCode visibilityError = NoError;
        bool hidden = false;
        if (hide) {
            API_ViewOptions options {};
            short modelViewIndex = 0;
            const GS::OnExit freeOptions ([&] { ACAPI_FreeGDLModelViewOptionsPtr (&options.modelViewOpt.gdlOptions); });
            visibilityError = ACAPI_Navigator_GetViewOptions (&options, &modelViewIndex);
            if (visibilityError == NoError) {
                options.onScreenViewOpt.camPathViewMode = API_CamPath_None;
                visibilityError = ACAPI_Navigator_ChangeViewOptions (&options, &modelViewIndex);
                API_ViewOptions readback {};
                const GS::OnExit freeReadback ([&] { ACAPI_FreeGDLModelViewOptionsPtr (&readback.modelViewOpt.gdlOptions); });
                if (visibilityError == NoError) visibilityError = ACAPI_Navigator_GetViewOptions (&readback);
                hidden = visibilityError == NoError && readback.onScreenViewOpt.camPathViewMode == API_CamPath_None;
            }
        }
        return GS::ObjectState ("pathGuid", APIGuidToString (pathGuid), "pathName", plan->name,
            "created", created, "reusedCount", static_cast<Int32> (reused),
            "verifiedCount", static_cast<Int32> (actual.size ()), "hiddenInPlan", hidden,
            "visibilityError", visibilityError, "inventory", after.Describe (), "savedProject", false);
    } catch (const std::exception& e) {
        return CreateErrorResponse (APIERR_GENERAL, GS::UniString (e.what ()));
    }
}
