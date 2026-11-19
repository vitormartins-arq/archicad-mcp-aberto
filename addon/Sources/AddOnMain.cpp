#include "APIEnvir.h"
#include "ACAPinc.h"

#include "ResourceIds.hpp"
#include "CameraCommands.hpp"
#include "GridCommands.hpp"
#include "ProjectSaveCommands.hpp"
#include "PlanViewCommands.hpp"
#include "CameraPathCommands.hpp"
#include "CameraViewCommands.hpp"
#include "ObjectReplacementCommands.hpp"

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
    err |= InitializeProjectSaveEvents ();
    err |= InstallCommand<GetCameraPathsCommand> ();
    err |= InstallCommand<PrepareCameraPathCommand> ();
    err |= InstallCommand<ApplyCameraPathCommand> ();
    err |= InstallCommand<SealCameraPathCommand> ();
    err |= InstallCommand<SaveCameraViewCommand> ();
    err |= InstallCommand<GetCameraViewsCommand> ();
    err |= InstallCommand<GetProjectSaveContextCommand> ();
    err |= InstallCommand<SaveProjectAsPLNCommand> ();
    err |= InstallCommand<SaveCurrentProjectPLNCommand> ();
    err |= InstallCommand<Get3DCameraCommand> ();
    err |= InstallCommand<Set3DCameraCommand> ();
    err |= InstallCommand<Save3DViewCommand> ();
    err |= InstallCommand<Get3DCutPlanesCommand> ();
    err |= InstallCommand<Set3DCutPlanesCommand> ();
    err |= InstallCommand<Show3DAllCommand> ();
    err |= InstallCommand<GetGridElementDefaultsCommand> ();
    err |= InstallCommand<GetGridElementsCommand> ();
    err |= InstallCommand<CreateGridElementsCommand> ();
    err |= InstallCommand<SaveStoryViewCommand> ();
    err |= InstallCommand<GetObjectReplacementDataCommand> ();
    err |= InstallCommand<ReplaceObjectLibrariesCommand> ();
#ifdef ServerMainVers_3000
    err |= InstallCommand<Get3DWindowImageCommand> ();
#endif
    return err;
}

GSErrCode FreeData (void)
{
    FreeProjectSaveEvents ();
    return NoError;
}
