#pragma once

#include "CommandBase.hpp"

// Grid Tool elements (structural grid lines). In the Archicad API a grid element is an
// API_ObjectID element with the variation APIVarId_GridElement ('GREL'), driven by a library
// part. Ported from Tapir (MIT, after 1.7.2: GridElementCommands.cpp), which Tapir 1.7.0
// does not have. When Tapir ships them, the MCP moves to Tapir's.

// The Grid Tool defaults: library part, size and GDL parameters of a new grid element.
class GetGridElementDefaultsCommand : public CommandBase
{
public:
    virtual GS::String GetName () const override;
    virtual GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    virtual GS::ObjectState Execute (const GS::ObjectState& parameters, GS::ProcessControl& processControl) const override;
};

// Every grid element with its position, angle, length and, optionally, GDL parameters.
class GetGridElementsCommand : public CommandBase
{
public:
    virtual GS::String GetName () const override;
    virtual GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    virtual GS::ObjectState Execute (const GS::ObjectState& parameters, GS::ProcessControl& processControl) const override;
};

// Creates grid elements from a start and an end point, with optional story, layer and GDL
// parameters, in one undo step.
class CreateGridElementsCommand : public CommandBase
{
public:
    virtual GS::String GetName () const override;
    virtual GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    virtual GS::ObjectState Execute (const GS::ObjectState& parameters, GS::ProcessControl& processControl) const override;
};
