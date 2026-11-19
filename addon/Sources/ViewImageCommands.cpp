#include "ViewImageCommands.hpp"
#include "Location.hpp"
#include <filesystem>
#include <string>

GS::String CaptureViewImageCommand::GetName () const { return "CaptureViewImage"; }

GS::Optional<GS::UniString> CaptureViewImageCommand::GetInputParametersSchema () const
{
    return GS::UniString (R"({"type":"object","properties":{"viewGuid":{"type":"string"},"outputPath":{"type":"string"},"crop":{"type":"boolean"}},"required":["outputPath"],"additionalProperties":false})");
}

GS::ObjectState CaptureViewImageCommand::Execute (const GS::ObjectState& parameters, GS::ProcessControl&) const
{
    GS::UniString output;
    if (!parameters.Get ("outputPath", output) || output.IsEmpty ())
        return CreateErrorResponse (APIERR_BADPARS, "Missing absolute PNG output path.");
    try {
        const std::string value = output.ToCStr (CC_UTF8).Get ();
        const std::filesystem::path path (std::u8string (
            reinterpret_cast<const char8_t*> (value.data ()), value.size ()));
        auto extension = path.extension ().string ();
        for (auto& ch : extension)
            if (ch >= 'A' && ch <= 'Z') ch = static_cast<char> (ch + ('a' - 'A'));
        if (!path.is_absolute () || extension != ".png" ||
            !std::filesystem::is_directory (path.parent_path ()) || std::filesystem::exists (path))
            return CreateErrorResponse (APIERR_BADPARS, "Output must be a new absolute PNG in an existing folder.");

        GS::UniString viewGuid;
        if (parameters.Get ("viewGuid", viewGuid) && !viewGuid.IsEmpty ()) {
            const GSErrCode goErr = ACAPI_View_GoToView (viewGuid.ToCStr ().Get ());
            if (goErr != NoError) return CreateErrorResponse (goErr, "Cannot open that View Map view.");
        }
        API_WindowInfo window {};
        const GSErrCode winErr = ACAPI_Window_GetCurrentWindow (&window);

        bool crop = true;
        parameters.Get ("crop", crop);
        IO::Location location (output);
        API_FileSavePars save = {};
        save.fileTypeID = APIFType_PNGFile;
        save.file = &location;
        API_SavePars_Picture picture = {};
        picture.colorDepth = APIColorDepth_TC24;
        picture.view2D = true;
        picture.crop = crop;
        picture.keepSelectionHighlight = false;
        const GSErrCode err = ACAPI_ProjectOperation_Save (&save, &picture);
        if (err != NoError)
            return CreateErrorResponse (err, "Archicad could not save this window as an image.");
        if (!std::filesystem::is_regular_file (path))
            return CreateErrorResponse (APIERR_GENERAL, "Image save returned, but no file was written.");
        GS::ObjectState response ("outputPath", output,
            "bytes", static_cast<double> (std::filesystem::file_size (path)));
        if (winErr == NoError)
            response.Add ("windowType", static_cast<Int32> (window.typeID));
        return response;
    } catch (const std::exception&) {
        return CreateErrorResponse (APIERR_BADPARS, "Output path validation or image save failed.");
    }
}
