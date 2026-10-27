#pragma once

#include "CommandBase.hpp"

// Saves a story's floor plan as a named View Map view with its own zoom box and,
// optionally, drawing scale and layer combination (the room enlargement views).
class SaveStoryViewCommand : public CommandBase
{
public:
    virtual GS::String GetName () const override;
    virtual GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    virtual GS::ObjectState Execute (const GS::ObjectState& parameters, GS::ProcessControl& processControl) const override;
};
