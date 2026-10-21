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

## Still needed

- A Local ID for this add-on, generated in Graphisoft's developer portal with the same
  Developer ID as LAB Blocos. The add-on must not reuse LAB Blocos's IDs.
- Build on the office PC (Visual Studio Build Tools 2022, DevKit 29 and 30 already there).
