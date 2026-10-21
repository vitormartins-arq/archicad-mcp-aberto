# Native add-on

Tapir is the main engine inside Archicad. Commands Tapir lacks go here, so the MCP does
not wait for a Tapir release (Vitor, 21/10/2026). Each one is also offered to Tapir
upstream; when Tapir ships it, the MCP moves to Tapir's and ours is retired.

If an add-on is built:
- Each Archicad major version needs its own build with the matching API DevKit
  (Windows: Visual Studio toolset v143, x64 for Archicad 29).
- The DevKit is downloaded from Graphisoft and never committed (`addon/devkit/` is ignored).
- The MDID (Developer ID and Local ID) must be issued by Graphisoft for this add-on.
  Example IDs or IDs borrowed from another add-on make Archicad reject it.

## Build

Windows, Visual Studio 2022 (toolset v143), CMake and the DevKit of each Archicad
version (`addon/devkit/` is ignored):

```
cmake -B addon/build -G "Visual Studio 17 2022" -A x64 -T v143 ^
  -DAC_VERSION=30 -DAC_API_DEVKIT_DIR=<DevKit>/Support ^
  -DAC_MDID_DEVELOPER_ID=<id> -DAC_MDID_LOCAL_ID=<id> addon
cmake --build addon/build --config RelWithDebInfo
```

CI (`.github/workflows/addon.yml`) compiles for Archicad 29 and 30 with a placeholder
MDID, so its `.apx` only proves the code builds. The build tooling in `Tools/` comes
from Tapir (MIT, `Tools/LICENSE-Tapir`).

## Commands

Namespace `ArchicadMcpAberto`, called with `API.ExecuteAddOnCommand`:

- `Get3DCamera`: the 3D projection (perspective camera and target in metres, or the
  parallel azimuth and projection mode).
- `Set3DCamera`: `{"perspective": {camera, target, viewCone?}}` or
  `{"parallel": {azimuth?, projectionMode?}}`; answers with the projection read back.
- `Get3DWindowImage` (Archicad 30 only): the 3D window as base64 PNG or JPG.

None is tested live yet; see `CAMERA.md`.
