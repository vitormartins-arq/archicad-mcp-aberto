#pragma once

#include "CommandBase.hpp"

// Saving the open project. The JSON API and Tapir 1.7 have no save command; these call
// ACAPI_ProjectOperation_Project and ACAPI_ProjectOperation_Save. Offered to Tapir too.

// Whether the project is untitled or Teamwork, and the path of its PLN.
class GetProjectSaveContextCommand : public CommandBase
{
public:
    virtual GS::String GetName () const override;
    virtual GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    virtual GS::ObjectState Execute (const GS::ObjectState& parameters, GS::ProcessControl& processControl) const override;
};

// Saves the open project, unsaved changes included, as a new PLN (Save As). Refuses an
// existing file, Teamwork and a project other than the one the caller expects.
class SaveProjectAsPLNCommand : public CommandBase
{
public:
    virtual GS::String GetName () const override;
    virtual GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    virtual GS::ObjectState Execute (const GS::ObjectState& parameters, GS::ProcessControl& processControl) const override;
};
