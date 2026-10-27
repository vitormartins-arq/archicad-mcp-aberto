#include "CommandBase.hpp"

constexpr const char* CommandNamespace = "ArchicadMcpAberto";

GS::String CommandBase::GetNamespace () const
{
    return CommandNamespace;
}

GS::Optional<GS::UniString> CommandBase::GetSchemaDefinitions () const
{
    return {};
}

GS::Optional<GS::UniString> CommandBase::GetResponseSchema () const
{
    return {};
}

API_AddOnCommandExecutionPolicy CommandBase::GetExecutionPolicy () const
{
    return API_AddOnCommandExecutionPolicy::ScheduleForExecutionOnMainThread;
}

void CommandBase::OnResponseValidationFailed (const GS::ObjectState& /*response*/) const
{
}

#ifdef ServerMainVers_2600
bool CommandBase::IsProcessWindowVisible () const
{
    return false;
}
#endif

GS::ObjectState CreateErrorResponse (GSErrCode errorCode, const GS::UniString& errorMessage)
{
    GS::ObjectState error;
    error.Add ("code", errorCode);
    error.Add ("message", errorMessage.ToCStr ().Get ());
    return GS::ObjectState ("error", error);
}
