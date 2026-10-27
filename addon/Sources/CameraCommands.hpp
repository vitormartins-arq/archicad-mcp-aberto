#pragma once

#include "CommandBase.hpp"

// View Map helpers shared with the plan view commands.
void SetItemName (API_NavigatorItem& item, const GS::UniString& name);
// Finds or creates folderPath in the View Map; the first name may be a folder at any depth.
GSErrCode ResolveViewMapFolder (const GS::Array<GS::UniString>& folderPath, API_Guid& parentGuid, GS::UniString& error);

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

// Saves the current 3D projection as a named view in the View Map, optionally in a folder.
class Save3DViewCommand : public CommandBase
{
public:
    virtual GS::String GetName () const override;
    virtual GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    virtual GS::ObjectState Execute (const GS::ObjectState& parameters, GS::ProcessControl& processControl) const override;
};

// Reads the 3D Cutting Planes dialog: on/off and each plane's raw values.
class Get3DCutPlanesCommand : public CommandBase
{
public:
    virtual GS::String GetName () const override;
    virtual GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    virtual GS::ObjectState Execute (const GS::ObjectState& parameters, GS::ProcessControl& processControl) const override;
};

// Sets the 3D Cutting Planes: on/off and the planes as read by Get3DCutPlanes.
class Set3DCutPlanesCommand : public CommandBase
{
public:
    virtual GS::String GetName () const override;
    virtual GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    virtual GS::ObjectState Execute (const GS::ObjectState& parameters, GS::ProcessControl& processControl) const override;
};

// "Show All in 3D" (clears the 3D element filter) and/or "Fit in Window" on the 3D window.
class Show3DAllCommand : public CommandBase
{
public:
    virtual GS::String GetName () const override;
    virtual GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    virtual GS::ObjectState Execute (const GS::ObjectState& parameters, GS::ProcessControl& processControl) const override;
};
