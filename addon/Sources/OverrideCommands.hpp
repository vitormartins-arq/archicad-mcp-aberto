#pragma once

#include "CommandBase.hpp"

// Graphic Overrides and Renovation Filters (Vitor, 16/11/2026: name the office template
// without the Archicad dialogs). Neither Tapir 1.7 nor the official JSON API reach them.
// In the Archicad 30 C API, override rules, rule groups (the folders of the Rules dialog)
// and combinations can be read and renamed; renovation filters can only be read (list,
// names, current one). Model View Options cannot be renamed by any API function.

// Every override combination, rule group and rule with its name, plus the current combination.
class GetGraphicOverridesCommand : public CommandBase
{
public:
    virtual GS::String GetName () const override;
    virtual GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    virtual GS::ObjectState Execute (const GS::ObjectState& parameters, GS::ProcessControl& processControl) const override;
};

// Renames override rules, rule groups and combinations by GUID, in one undo step; one result
// per item. Built-in items are refused by Archicad.
class RenameGraphicOverridesCommand : public CommandBase
{
public:
    virtual GS::String GetName () const override;
    virtual GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    virtual GS::ObjectState Execute (const GS::ObjectState& parameters, GS::ProcessControl& processControl) const override;
};

// Every renovation filter with its name, plus the current one. Read only: the API has no
// call to rename a filter or to read its settings.
class GetRenovationFiltersCommand : public CommandBase
{
public:
    virtual GS::String GetName () const override;
    virtual GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    virtual GS::ObjectState Execute (const GS::ObjectState& parameters, GS::ProcessControl& processControl) const override;
};
