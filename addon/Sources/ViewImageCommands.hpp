#pragma once
#include "CommandBase.hpp"

// Opens a View Map view (optional) and saves the active window as a PNG, so a client
// can look at the result of its edits, like a viewport screenshot. Never edits or saves
// the project file.
class CaptureViewImageCommand : public CommandBase {
public:
    GS::String GetName () const override;
    GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    GS::ObjectState Execute (const GS::ObjectState&, GS::ProcessControl&) const override;
};
