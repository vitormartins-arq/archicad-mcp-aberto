#include "APIEnvir.h"
#include "ACAPinc.h"

#include "ResourceIds.hpp"
#include "CameraCommands.hpp"

template <typename CommandType>
static GSErrCode InstallCommand ()
{
    return ACAPI_AddOnAddOnCommunication_InstallAddOnCommandHandler (GS::NewOwned<CommandType> ());
}

API_AddonType CheckEnvironment (API_EnvirParams* envir)
{
    RSGetIndString (&envir->addOnInfo.name, ID_ADDON_INFO, ID_ADDON_INFO_NAME, ACAPI_GetOwnResModule ());
    RSGetIndString (&envir->addOnInfo.description, ID_ADDON_INFO, ID_ADDON_INFO_DESC, ACAPI_GetOwnResModule ());
    return APIAddon_Preload;
}

GSErrCode RegisterInterface (void)
{
    return NoError;
}

GSErrCode Initialize (void)
{
    GSErrCode err = NoError;
    err |= InstallCommand<Get3DCameraCommand> ();
    err |= InstallCommand<Set3DCameraCommand> ();
#ifdef ServerMainVers_3000
    err |= InstallCommand<Get3DWindowImageCommand> ();
#endif
    return err;
}

GSErrCode FreeData (void)
{
    return NoError;
}
