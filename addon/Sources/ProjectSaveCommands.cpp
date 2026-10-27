#include "ProjectSaveCommands.hpp"
#include "Location.hpp"
#include "GSGuid.hpp"
#include <filesystem>
#include <string>

namespace {
GS::UniString Session ()
{
    static const GS::UniString session = GS::Guid (GS::Guid::GenerateGuid).ToUniString ();
    return session;
}
GS::UniString& Epoch ()
{
    static GS::UniString epoch = GS::Guid (GS::Guid::GenerateGuid).ToUniString ();
    return epoch;
}
GSErrCode __ACENV_CALL OnProjectEvent (API_NotifyEventID event, Int32)
{
    if (event == APINotify_New || event == APINotify_NewAndReset ||
        event == APINotify_Open || event == APINotify_Close)
        Epoch () = GS::Guid (GS::Guid::GenerateGuid).ToUniString ();
    return NoError;
}
GS::ObjectState Context (const API_ProjectInfo& info)
{
    GS::UniString path;
    if (info.location != nullptr)
        info.location->ToPath (&path);
    // Decimal string preserves UInt64 without JSON floating-point truncation.
    return GS::ObjectState ("sessionId", Session (), "projectEpoch", Epoch (),
        "projectPath", path, "modificationStamp", GS::UniString (std::to_string (info.modiStamp).c_str ()),
        "untitled", info.untitled, "teamwork", info.teamwork);
}
}

GSErrCode InitializeProjectSaveEvents ()
{
    return ACAPI_ProjectOperation_CatchProjectEvent (API_AllProjectNotificationMask, OnProjectEvent);
}
void FreeProjectSaveEvents ()
{
    ACAPI_ProjectOperation_CatchProjectEvent (API_AllProjectNotificationMask, nullptr);
}
GS::String GetProjectSaveContextCommand::GetName () const { return "GetProjectSaveContext"; }
GS::Optional<GS::UniString> GetProjectSaveContextCommand::GetInputParametersSchema () const
{
    return GS::UniString (R"({"type":"object","additionalProperties":false})");
}
GS::ObjectState GetProjectSaveContextCommand::Execute (const GS::ObjectState&, GS::ProcessControl&) const
{
    API_ProjectInfo info;
    const GSErrCode err = ACAPI_ProjectOperation_Project (&info);
    if (err != NoError) return CreateErrorResponse (err, "Cannot read project save context.");
    return Context (info);
}
GS::String SaveProjectAsPLNCommand::GetName () const { return "SaveProjectAsPLN"; }
GS::Optional<GS::UniString> SaveProjectAsPLNCommand::GetInputParametersSchema () const
{
    return GS::UniString (R"({"type":"object","properties":{"destinationPath":{"type":"string"},"sessionId":{"type":"string"},"projectEpoch":{"type":"string"},"projectPath":{"type":"string"},"modificationStamp":{"type":"string"},"untitled":{"type":"boolean"},"teamwork":{"type":"boolean"}},"required":["destinationPath","sessionId","projectEpoch","projectPath","modificationStamp","untitled","teamwork"],"additionalProperties":false})");
}
GS::ObjectState SaveProjectAsPLNCommand::Execute (const GS::ObjectState& parameters, GS::ProcessControl&) const
{
    API_ProjectInfo info;
    GSErrCode err = ACAPI_ProjectOperation_Project (&info);
    if (err != NoError) return CreateErrorResponse (err, "Cannot read project before save.");
    if (info.teamwork) return CreateErrorResponse (APIERR_BADPARS, "Teamwork Save As is refused.");
    const GS::ObjectState current = Context (info);
    for (const char* key : {"sessionId", "projectEpoch", "projectPath", "modificationStamp"}) {
        GS::UniString expected, actual;
        if (!parameters.Get (key, expected) || !current.Get (key, actual) || expected != actual)
            return CreateErrorResponse (APIERR_BADPARS, "Stale save context; request a new preview.");
    }
    bool untitled = false, teamwork = true;
    if (!parameters.Get ("untitled", untitled) || !parameters.Get ("teamwork", teamwork) ||
        untitled != info.untitled || teamwork != info.teamwork)
        return CreateErrorResponse (APIERR_BADPARS, "Project kind changed since preview.");
    GS::UniString destination;
    if (!parameters.Get ("destinationPath", destination))
        return CreateErrorResponse (APIERR_BADPARS, "Missing absolute PLN path.");
    try {
        const std::string value = destination.ToCStr (CC_UTF8).Get ();
        const auto path = std::filesystem::u8path (value);
        auto extension = path.extension ().string ();
        for (auto& ch : extension) if (ch >= 'A' && ch <= 'Z') ch += 'a' - 'A';
        if (!path.is_absolute () || extension != ".pln" ||
            !std::filesystem::is_directory (path.parent_path ()) || std::filesystem::exists (path))
            return CreateErrorResponse (APIERR_BADPARS, "Destination must be a new absolute PLN in an existing folder.");
        for (auto part = path; !part.empty ();) {
            if (std::filesystem::is_symlink (std::filesystem::symlink_status (part)))
                return CreateErrorResponse (APIERR_BADPARS, "Linked destinations are refused.");
            const auto parent = part.parent_path ();
            if (parent == part) break;
            part = parent;
        }
        IO::Location location (destination);
        API_FileSavePars save = {};
        save.fileTypeID = APIFType_PlanFile;
        save.file = &location;
        // Save the in-memory project, outside any Undo/non-Undo command wrapper.
        // FileSavePars has no atomic no-replace option; callers must not write this path concurrently.
        err = ACAPI_ProjectOperation_Save (&save);
        if (err != NoError) return CreateErrorResponse (err, "Native Save As returned an error; inspect before retrying.");
        API_ProjectInfo after;
        err = ACAPI_ProjectOperation_Project (&after);
        if (err != NoError) return CreateErrorResponse (err, "Save returned, but context read-back failed.");
        return Context (after);
    } catch (const std::exception&) {
        return CreateErrorResponse (APIERR_BADPARS, "File path validation or save inspection failed.");
    }
}
