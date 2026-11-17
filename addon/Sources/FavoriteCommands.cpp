#include "FavoriteCommands.hpp"
#include "ACAPI/Favorite.hpp"

#include <optional>

// Archicad 29/30 Favorite Manager (ACAPI::Favorite). RenameFavorite and RenameFolder keep
// the favorite's settings, classifications and properties: nothing is recreated. Both need
// a NotUndoable command scope (ACAPI_CallCommand), so these renames cannot be undone with
// Ctrl+Z; save a new revision before calling.

namespace {
using ACAPI::Favorite::Favorite;
using ACAPI::Favorite::FavoriteFolder;
using ACAPI::Favorite::FavoriteManager;

GS::Array<GS::UniString> PathOf (const FavoriteFolder& folder)
{
    GS::Array<GS::UniString> path;
    for (const auto& part : folder.GetPath ()) path.Push (part);
    return path;
}

void Walk (const FavoriteFolder& folder, GS::Array<GS::ObjectState>& folders,
           GS::Array<GS::ObjectState>& favorites)
{
    const GS::Array<GS::UniString> path = PathOf (folder);
    for (const auto& favorite : folder.GetFavorites ()) {
        const auto name = favorite.GetName ();
        if (name.IsErr ()) continue;
        GS::ObjectState row;
        row.Add ("name", name.Unwrap ());
        row.Add ("folder", path);
        const auto type = favorite.GetElementType ();
        if (type.IsOk ()) {
            row.Add ("typeID", static_cast<Int32> (type.Unwrap ().typeID));
            row.Add ("variationID", static_cast<Int32> (type.Unwrap ().variationID));
        }
        favorites.Push (row);
    }
    for (const auto& sub : folder.GetSubFolders ()) {
        GS::ObjectState row;
        row.Add ("path", PathOf (sub));
        folders.Push (row);
        Walk (sub, folders, favorites);
    }
}

std::optional<FavoriteFolder> FindFolder (const FavoriteManager& manager, const GS::Array<GS::UniString>& path)
{
    auto root = manager.GetRootFolder ();
    if (root.IsErr ()) return std::nullopt;
    FavoriteFolder current = root.Unwrap ();
    for (const auto& part : path) {
        std::optional<FavoriteFolder> next;
        for (const auto& sub : current.GetSubFolders ()) {
            const auto name = sub.GetName ();
            if (name.IsOk () && name.Unwrap () == part) {
                if (next.has_value ()) return std::nullopt;  // ambiguous
                next = sub;
            }
        }
        if (!next.has_value ()) return std::nullopt;
        current = *next;
    }
    return current;
}

bool ValidName (const GS::UniString& name)
{
    GS::UniString trimmed = name;
    trimmed.Trim ();
    return !trimmed.IsEmpty () && name.GetLength () < 256 &&
           name.FindFirst (GS::UniChar (char16_t {0})) == MaxUIndex;
}

GS::ObjectState Row (const GS::UniString& kind, GSErrCode error, const char* message)
{
    GS::ObjectState row;
    row.Add ("kind", kind);
    row.Add ("success", error == NoError);
    if (error != NoError) {
        GS::ObjectState detail;
        detail.Add ("code", static_cast<Int32> (error));
        detail.Add ("message", GS::UniString (message));
        row.Add ("error", detail);
    }
    return row;
}
}

GS::String GetFavoriteTreeCommand::GetName () const { return "GetFavoriteTree"; }

GS::Optional<GS::UniString> GetFavoriteTreeCommand::GetInputParametersSchema () const
{
    return R"({"type":"object","properties":{},"additionalProperties":false})";
}

GS::ObjectState GetFavoriteTreeCommand::Execute (const GS::ObjectState&, GS::ProcessControl&) const
{
    const FavoriteManager manager = ACAPI::Favorite::GetFavoriteManager ();
    const auto root = manager.GetRootFolder ();
    if (root.IsErr ()) return CreateErrorResponse (root.UnwrapErr ().kind, "Favorites root folder not available.");
    GS::Array<GS::ObjectState> folders, favorites;
    Walk (root.Unwrap (), folders, favorites);
    GS::ObjectState result;
    auto addFolder = result.AddList<GS::ObjectState> ("folders");
    for (const auto& row : folders) addFolder (row);
    auto addFavorite = result.AddList<GS::ObjectState> ("favorites");
    for (const auto& row : favorites) addFavorite (row);
    return result;
}

GS::String RenameFavoritesCommand::GetName () const { return "RenameFavoritesAndFolders"; }

GS::Optional<GS::UniString> RenameFavoritesCommand::GetInputParametersSchema () const
{
    return R"({"type":"object","properties":{)"
           R"("folders":{"type":"array","maxItems":500,"items":{"type":"object","properties":{"path":{"type":"array","minItems":1,"items":{"type":"string"}},"newName":{"type":"string"}},"required":["path","newName"],"additionalProperties":false}},)"
           R"("favorites":{"type":"array","maxItems":2000,"items":{"type":"object","properties":{"name":{"type":"string"},"newName":{"type":"string"}},"required":["name","newName"],"additionalProperties":false}})"
           R"(},"additionalProperties":false})";
}

// Folders are renamed first, in request order: send the deepest paths first, since a
// folder's path changes once one of its parents is renamed. Each item is read back.
GS::ObjectState RenameFavoritesCommand::Execute (const GS::ObjectState& input, GS::ProcessControl&) const
{
    GS::Array<GS::ObjectState> folderItems, favoriteItems;
    if (input.Contains ("folders")) input.Get ("folders", folderItems);
    if (input.Contains ("favorites")) input.Get ("favorites", favoriteItems);
    if (folderItems.IsEmpty () && favoriteItems.IsEmpty ())
        return CreateErrorResponse (APIERR_BADPARS, "Nothing to rename.");

    const FavoriteManager manager = ACAPI::Favorite::GetFavoriteManager ();
    GS::Array<GS::ObjectState> answers;
    const GSErrCode batchError = ACAPI_CallCommand ("Rename favorites", [&] () -> GSErrCode {
        for (const auto& item : folderItems) {
            GS::Array<GS::UniString> path;
            GS::UniString newName;
            item.Get ("path", path);
            item.Get ("newName", newName);
            GSErrCode error = NoError;
            const char* message = "";
            if (!ValidName (newName)) {
                error = APIERR_BADNAME;
                message = "Blank, invalid or overlong folder name.";
            } else if (auto folder = FindFolder (manager, path); !folder.has_value ()) {
                error = APIERR_BADNAME;
                message = "Folder path not found, or ambiguous.";
            } else if (path.GetLast () != newName) {
                const auto renamed = manager.RenameFolder (*folder, newName);
                if (renamed.IsErr ()) {
                    error = renamed.UnwrapErr ().kind;
                    message = "RenameFolder failed (a sibling may already use this name).";
                } else {
                    GS::Array<GS::UniString> after = path;
                    after[after.GetSize () - 1] = newName;
                    if (!FindFolder (manager, after).has_value ()) {
                        error = APIERR_GENERAL;
                        message = "Folder renamed, but the new path could not be read back.";
                    }
                }
            }
            GS::ObjectState row = Row ("folder", error, message);
            row.Add ("path", path);
            row.Add ("newName", newName);
            answers.Push (row);
        }
        for (const auto& item : favoriteItems) {
            GS::UniString name, newName;
            item.Get ("name", name);
            item.Get ("newName", newName);
            GSErrCode error = NoError;
            const char* message = "";
            const auto favorite = manager.GetFavoriteByName (name);
            if (!ValidName (newName)) {
                error = APIERR_BADNAME;
                message = "Blank, invalid or overlong favorite name.";
            } else if (favorite.IsErr ()) {
                error = APIERR_BADNAME;
                message = "Favorite not found.";
            } else if (name != newName) {
                const auto existing = manager.GetFavoriteByName (newName);
                // Archicad may match names without case: a case-only rename finds itself.
                if (existing.IsOk () && !newName.IsEqual (name, GS::CaseInsensitive)) {
                    error = APIERR_NAMEALREADYUSED;
                    message = "Another favorite already uses this name.";
                } else {
                    const auto renamed = manager.RenameFavorite (favorite.Unwrap (), newName);
                    if (renamed.IsErr ()) {
                        error = renamed.UnwrapErr ().kind;
                        message = "RenameFavorite failed.";
                    } else {
                        const auto after = manager.GetFavoriteByName (newName);
                        if (after.IsErr () || after.Unwrap ().GetName ().Unwrap () != newName) {
                            error = APIERR_GENERAL;
                            message = "Favorite renamed, but the new name could not be read back.";
                        }
                    }
                }
            }
            GS::ObjectState row = Row ("favorite", error, message);
            row.Add ("name", name);
            row.Add ("newName", newName);
            answers.Push (row);
        }
        return NoError;
    });
    if (batchError != NoError) return CreateErrorResponse (batchError, "Rename favorites command failed.");
    GS::ObjectState result;
    auto add = result.AddList<GS::ObjectState> ("results");
    for (const auto& row : answers) add (row);
    return result;
}
