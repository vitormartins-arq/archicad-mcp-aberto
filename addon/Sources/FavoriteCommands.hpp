#pragma once
#include "CommandBase.hpp"

// Favorites palette tree: folders and favorites of every element type, with paths.
class GetFavoriteTreeCommand : public CommandBase {
public:
    GS::String GetName () const override;
    GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    GS::ObjectState Execute (const GS::ObjectState&, GS::ProcessControl&) const override;
};

// Renames favorites (by exact name) and folders (by exact path), keeping every setting.
class RenameFavoritesCommand : public CommandBase {
public:
    GS::String GetName () const override;
    GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    GS::ObjectState Execute (const GS::ObjectState&, GS::ProcessControl&) const override;
};
