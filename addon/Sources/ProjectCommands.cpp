#include "ProjectCommands.hpp"

#include "FileSystem.hpp"

static GSErrCode GetProjectState (bool& untitled, bool& teamwork, GS::UniString& path, GS::UniString& name)
{
    API_ProjectInfo info;
    GSErrCode err = ACAPI_ProjectOperation_Project (&info);
    if (err != NoError) {
        return err;
    }
    untitled = info.untitled;
    teamwork = info.teamwork;
    path.Clear ();
    name.Clear ();
    if (!info.untitled && info.location != nullptr) {
        info.location->ToPath (&path);
    }
    if (info.projectName != nullptr) {
        name = *info.projectName;
    }
    return NoError;
}

static GS::ObjectState CreateContextResponse (bool untitled, bool teamwork, const GS::UniString& path, const GS::UniString& name)
{
    GS::ObjectState response;
    response.Add ("untitled", untitled);
    response.Add ("teamwork", teamwork);
    if (!path.IsEmpty ()) {
        response.Add ("projectPath", path);
    }
    if (!name.IsEmpty ()) {
        response.Add ("projectName", name);
    }
    return response;
}

GS::String GetProjectSaveContextCommand::GetName () const
{
    return "GetProjectSaveContext";
}

GS::Optional<GS::UniString> GetProjectSaveContextCommand::GetInputParametersSchema () const
{
    return R"({
        "type": "object",
        "properties": {},
        "additionalProperties": false
    })";
}

GS::ObjectState GetProjectSaveContextCommand::Execute (const GS::ObjectState& /*parameters*/, GS::ProcessControl& /*processControl*/) const
{
    bool untitled = true;
    bool teamwork = false;
    GS::UniString path;
    GS::UniString name;
    GSErrCode err = GetProjectState (untitled, teamwork, path, name);
    if (err != NoError) {
        return CreateErrorResponse (err, "Failed to read the project info.");
    }
    return CreateContextResponse (untitled, teamwork, path, name);
}

GS::String SaveProjectAsPLNCommand::GetName () const
{
    return "SaveProjectAsPLN";
}

GS::Optional<GS::UniString> SaveProjectAsPLNCommand::GetInputParametersSchema () const
{
    return R"({
        "type": "object",
        "properties": {
            "destinationPath": {"type": "string", "minLength": 5, "maxLength": 1000, "description": "Absolute path of the new .pln file. It must not exist."},
            "expectedProjectPath": {"type": "string", "maxLength": 1000, "description": "Path of the PLN the caller saw open; empty for an untitled project."}
        },
        "additionalProperties": false,
        "required": ["destinationPath", "expectedProjectPath"]
    })";
}

GS::ObjectState SaveProjectAsPLNCommand::Execute (const GS::ObjectState& parameters, GS::ProcessControl& /*processControl*/) const
{
    GS::UniString destinationPath;
    GS::UniString expectedPath;
    parameters.Get ("destinationPath", destinationPath);
    parameters.Get ("expectedProjectPath", expectedPath);

    bool untitled = true;
    bool teamwork = false;
    GS::UniString path;
    GS::UniString name;
    GSErrCode err = GetProjectState (untitled, teamwork, path, name);
    if (err != NoError) {
        return CreateErrorResponse (err, "Failed to read the project info.");
    }
    if (teamwork) {
        return CreateErrorResponse (APIERR_REFUSEDCMD, "Teamwork projects are not saved by this command.");
    }
    if (!path.IsEqual (expectedPath, GS::CaseInsensitive)) {
        return CreateErrorResponse (APIERR_BADPARS, "Another project is open now; run a new preview.");
    }

    IO::Location destination (destinationPath);
    if (IO::fileSystem.Contains (destination)) {
        return CreateErrorResponse (APIERR_BADPARS, "The destination file already exists.");
    }

    API_FileSavePars savePars {};
    savePars.fileTypeID = APIFType_PlanFile;
    savePars.file = &destination;
    err = ACAPI_ProjectOperation_Save (&savePars);
    if (err != NoError) {
        return CreateErrorResponse (err, "Archicad refused to save the project (read-only, demo version or busy).");
    }

    err = GetProjectState (untitled, teamwork, path, name);
    if (err != NoError) {
        return CreateErrorResponse (err, "Saved, but failed to read the project info again.");
    }
    return CreateContextResponse (untitled, teamwork, path, name);
}
