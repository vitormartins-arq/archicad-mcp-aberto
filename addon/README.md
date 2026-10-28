# Native add-on

Tapir is the main engine inside Archicad. Commands Tapir lacks go here, so the MCP does
not wait for a Tapir release (Vitor, 21/10/2026). Each one is also offered to Tapir
upstream; when Tapir ships it, the MCP moves to Tapir's and ours is retired.

If an add-on is built:
- Each Archicad major version needs its own build with the matching API DevKit
  (Windows: Visual Studio toolset v143, x64 for Archicad 29).
- The DevKit is downloaded from Graphisoft and never committed (`addon/devkit/` is ignored).
- The MDID (Developer ID and Local ID) must be issued by Graphisoft for this add-on.
  Ours is Developer ID 1110659426, Local ID 287719994 ("Archicad MCP Aberto"), the
  CMake defaults. Example IDs or IDs borrowed from another add-on make Archicad reject it.

## Build

Windows, Visual Studio 2022 (toolset v143), CMake and the DevKit of each Archicad
version (`addon/devkit/` is ignored):

```
cmake -B addon/build -G "Visual Studio 17 2022" -A x64 -T v143 ^
  -DAC_VERSION=30 -DAC_API_DEVKIT_DIR=<DevKit>/Support addon
cmake --build addon/build --config RelWithDebInfo
```

CI (`.github/workflows/addon.yml`) builds the `.apx` for Archicad 29 and 30 with the
real MDID and keeps it as a run artifact. The build tooling in `Tools/` comes
from Tapir (MIT, `Tools/LICENSE-Tapir`).

## Commands

Namespace `ArchicadMcpAberto`, called with `API.ExecuteAddOnCommand`:

- `Get3DCamera`: the 3D projection (perspective camera and target in metres, or the
  parallel azimuth and projection mode).
- `Set3DCamera`: `{"perspective": {camera, target, viewCone?}}` or
  `{"parallel": {azimuth?, projectionMode?}}`; answers with the projection read back.
- `Save3DView`: `{"name", "folderPath"?}` saves the current 3D projection as a View
  Map view, creating the folders it needs.
- `Get3DCutPlanes` / `Set3DCutPlanes`: the 3D Cutting Planes dialog, planes passed raw.
- `Show3DAll`: Show All in 3D and, optionally, Fit in Window, for when the model
  disappears from the 3D window.
- `Get3DWindowImage` (Archicad 30 only): the 3D window as base64 PNG or JPG.
- `SaveStoryView`: `{"storyIndex", "name", "folderPath"?, "zoom": {xMin, yMin, xMax,
  yMax}, "drawingScale"?, "layerCombination"?}` saves the story's floor plan as a View
  Map view with that zoom box (metres), scale denominator and layer combination, and
  answers with the view settings read back. Folders as in `Save3DView`.
- `GetGridElementDefaults`, `GetGridElements`, `CreateGridElements`: grid lines (Grid
  Tool elements), ported from Tapir's commands added after 1.7.2 (MIT). Coordinates in
  metres; `CreateGridElements` takes `begCoordinate`, `endCoordinate` and optional
  `floorIndex`, `layerIndex`, `lengthMode` and GDL `parameters`, all in one Undo step.
- `SaveCameraView`: `{"name", "pathName", "folderPath"?, "viewMap"?}` saves the current
  perspective as a camera at the end of a camera path (created when missing), with the
  name as the camera ID, and, unless `viewMap` is false, clones it into the View Map.
- `GetCameraViews`: `{"map"?: "ViewMap" | "ProjectMap"}` lists the camera items with
  their camera and camera path.
- Renaming Project Map cameras is not offered: Archicad refuses it even through the
  API (ChangeMemo ignored, ChangeNavigatorItem 0x81060065, live AC30, 28/10/2026).

Angles are in radians on the MCP side; Archicad keeps them in degrees and the commands
convert. A perspective camera defaults to a 60 degree view cone. First live test
(AC30 build 3001 BRA, 21/10/2026) in `CAMERA.md`; how to place cameras in
`docs/3D_SCENES.md`.
