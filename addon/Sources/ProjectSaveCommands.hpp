#pragma once
#include "CommandBase.hpp"

GSErrCode InitializeProjectSaveEvents ();
void FreeProjectSaveEvents ();

class GetProjectSaveContextCommand : public CommandBase {
public:
    GS::String GetName () const override;
    GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    GS::ObjectState Execute (const GS::ObjectState&, GS::ProcessControl&) const override;
};

class SaveProjectAsPLNCommand : public CommandBase {
public:
    GS::String GetName () const override;
    GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    GS::ObjectState Execute (const GS::ObjectState&, GS::ProcessControl&) const override;
};

// Explicit save of the currently open standalone PLN to the SAME path.
// Callers preserve/verify their pre-task backup first; never retries a native save.
class SaveCurrentProjectPLNCommand : public CommandBase {
public:
    GS::String GetName () const override;
    GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    GS::ObjectState Execute (const GS::ObjectState&, GS::ProcessControl&) const override;
};
