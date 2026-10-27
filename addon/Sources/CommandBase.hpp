#pragma once

#include "APIEnvir.h"
#include "ACAPinc.h"

#include "ObjectState.hpp"

// Every command answers {"error": {code, message}} on failure, like Tapir. The response
// schema stays empty so Archicad never swaps that error for a validation error.
class CommandBase : public API_AddOnCommand
{
public:
    virtual GS::String GetNamespace () const override final;
    virtual GS::Optional<GS::UniString> GetSchemaDefinitions () const override final;
    virtual GS::Optional<GS::UniString> GetResponseSchema () const override final;
    virtual API_AddOnCommandExecutionPolicy GetExecutionPolicy () const override final;
    virtual void OnResponseValidationFailed (const GS::ObjectState& response) const override final;
#ifdef ServerMainVers_2600
    virtual bool IsProcessWindowVisible () const override final;
#endif
};

GS::ObjectState CreateErrorResponse (GSErrCode errorCode, const GS::UniString& errorMessage);
