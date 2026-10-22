# Camera and 3D scenes: what the Archicad 30 API offers

Research for queue item C20, read from the Archicad 30 C++ API reference
(github.com/GRAPHISOFT/archicad-api-devkit, `docs/`). Nothing here is tested live yet.

| Need | Archicad 30 API | Notes |
|---|---|---|
| Read the 3D camera | `ACAPI_View_Get3DProjectionSets (API_3DProjectionInfo*)` | `isPersp` picks perspective or parallel |
| Set the 3D camera | `ACAPI_View_Change3DProjectionSets (API_3DProjectionInfo*, bool* switchOnly)` | Perspective: `API_PerspPars` with `pos`, `target` (x, y), `cameraZ`, `targetZ`, `viewCone`, `rollAngle`, `distance`, `azimuth`, `isTwoPointPersp`. Parallel: `API_AxonoPars` with `azimuth`, `projMod`, `tranmat`. A non-zero `camGuid` or `actCamSet` ties the view to a floor plan camera instead |
| Look at the result | `ACAPI_View_GetCurrentImage (NewDisplay::NativeImage&, const API_ImageSource&)` | Image of the current 3D or rendering window; `APIERR_BADWINDOW` when the front window is not one of them |
| Render to a picture | `ACAPI_Rendering_PhotoRender`, `ACAPI_Rendering_SetCurrentRenderingScene` | For later, slower |
| Fit the model | `ACAPI_View_ShowAllIn3D`, `ACAPI_View_ZoomToElements` | |
| Save as a view | Tapir 1.7.0 `CreateViewsInViewMap` (clone of the Project Map 3D item, own name and folder) | `API_NavigatorView` has no camera field, so whether the clone keeps the camera set just before must be checked live |

## Planned add-on commands

Namespace `ArchicadMcpAberto`, called through `API.ExecuteAddOnCommand` like Tapir.

1. `Get3DCamera`: the current projection, in metres and radians.
2. `Set3DCamera`: perspective (camera point, target point, view cone) or parallel
   (azimuth, projection type), then the 3D window is rebuilt.
3. `Get3DWindowImage`: the 3D window as a PNG file in a given folder, so the model can
   check the scene before saving it.

The MCP tool `create_3d_scenes` then reads the model's 3D box, picks angles (corner
axonometrics, eye-level perspectives at 1.60 m), sets each camera, saves each scene with
`CreateViewsInViewMap` into a View Map folder, and checks it with the image.

## Live test, 21/10/2026

Archicad 30 build 3001 BRA, Tapir 1.7.0, a real project opened read-only for elements
(only the 3D camera changed, nothing saved), add-on built from de83f14.

- `Set3DCamera` perspective: camera and target read back exactly as sent, three times.
- Archicad stores the perspective azimuth in degrees, 0..360, equal to
  atan2(camera.y - target.y, camera.x - target.x); it recomputes it from camera and target.
- The view cone is in degrees too (60 by default). Sending 1.047 (60 degrees in radians)
  gave a 1.047 degree cone and an almost black 3D window. The parallel azimuth is in
  degrees as well.
- Going from parallel back to perspective without a view cone read back viewCone 0 and
  twoPointPerspective true: leftovers from the parallel settings in the union.
- `Get3DWindowImage`: five 2378x1080 PNGs, all fine.

Fixed after the test: radians at the MCP side, degrees inside, and default perspective
settings when switching from parallel. Not yet retested live.

## Live test, 22/10/2026

Archicad 30 build 3001 BRA, office PC, same project, add-on from 07210e2 (Tapir not
loaded). `Save3DView` into `["02 | MODELO 3D", "AMBIENTES", "04 PESO LIVRE E
ARTICULADO"]` created the nested folders, and opening the saved view with the 3D camera
elsewhere restored the view's own camera (checked by Vitor).

## Still needed

- Retest the angle fix live (view cone, parallel azimuth, parallel to perspective).
