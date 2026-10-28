#pragma once
#include "CommandBase.hpp"

// Saves the current 3D perspective as a camera at the end of a camera path and puts that
// camera in the View Map. BIMx loads cameras faster than saved 3D views.
class SaveCameraViewCommand : public CommandBase {
public:
    GS::String GetName () const override;
    GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    GS::ObjectState Execute (const GS::ObjectState&, GS::ProcessControl&) const override;
};
// Lists the camera items of the View Map with the camera element each one shows.
class GetCameraViewsCommand : public CommandBase {
public:
    GS::String GetName () const override;
    GS::Optional<GS::UniString> GetInputParametersSchema () const override;
    GS::ObjectState Execute (const GS::ObjectState&, GS::ProcessControl&) const override;
};
