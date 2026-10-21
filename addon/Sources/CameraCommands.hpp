#pragma once

#include "CommandBase.hpp"

// Reads the 3D projection (camera) of the "3D Projection Settings" dialog.
class Get3DCameraCommand : public CommandBase
{
public:
    virtual GS::String GetName () const override;
    virtual GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    virtual GS::ObjectState Execute (const GS::ObjectState& parameters, GS::ProcessControl& processControl) const override;
};

// Sets a perspective (camera and target points, view cone) or a parallel projection.
class Set3DCameraCommand : public CommandBase
{
public:
    virtual GS::String GetName () const override;
    virtual GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    virtual GS::ObjectState Execute (const GS::ObjectState& parameters, GS::ProcessControl& processControl) const override;
};

#ifdef ServerMainVers_3000
// The current 3D window as a base64 PNG (ACAPI_View_GetCurrentImage, new in Archicad 30).
class Get3DWindowImageCommand : public CommandBase
{
public:
    virtual GS::String GetName () const override;
    virtual GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    virtual GS::ObjectState Execute (const GS::ObjectState& parameters, GS::ProcessControl& processControl) const override;
};
#endif
