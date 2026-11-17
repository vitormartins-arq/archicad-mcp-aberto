#pragma once
#include "CommandBase.hpp"

class RenameAttributesCommand : public CommandBase {
public:
    GS::String GetName () const override;
    GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    GS::ObjectState Execute (const GS::ObjectState&, GS::ProcessControl&) const override;
};
