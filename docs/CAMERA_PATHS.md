# Physical camera paths from saved 3D views

Work in progress: new native GetCameraPaths, PrepareCameraPath and ApplyCameraPath,
plus guarded SaveCurrentProjectPLN for same-file saving. These create actual
API_CameraType/API_CamSetType elements; Set3DCamera/Save3DView alone do not.

Read exact projection and effective view settings by activating saved views through
ACAPI_View_GoToView, pairing StoreViewSettings, restoring original window, projection,
cutting planes, filters and selection. Capture named styles, renovation/override,
effective layer flags, native model-view options and GDL parameter checksums. Native
ABI option bytes are conservative within-process comparison data, not portable fixtures.
Do not claim grouped configurations certify a published BIMx model.

Only perspective views become cameras. Keep parallel views and 3D documents intact.
One path per representation, preserving Navigator order. Attach persistent source-view
GUID metadata to new cameras. Reuse only unchanged managed-prefix paths; ambiguous,
unmanaged or reordered targets are preserved and refused instead of duplicated.

Native previews bind project session/epoch/path/stamp, source snapshots and complete
camera inventory, expire after ten minutes and are consumed before any mutation.
Creation is an Undo transaction with parameter/source/order readback. Camera path
visibility uses onScreenViewOpt.camPathViewMode=API_CamPath_None without editing layers.
No Publisher modification, publication, upload or deletion.

The authorized workflow maintains the working PLN name: verified _backup copies in
00 - Anteriores before model changes, then native same-path save. This supersedes revision
increments as the owner's normal workflow. Never ask the owner to manufacture an
untitled/test project or manually rename/save files for an already authorized task.
Do not conflate an old disk copy with pending in-memory edits; preserve disk baseline
before checkpoint save and verify the in-memory checkpoint too. Never blindly retry
an unknown result. Native/runtime tests and client orchestration are pending.
