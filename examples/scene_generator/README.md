# Scene generator

Scripts used on 22/10/2026 to generate interior, exterior and axonometric 3D views of a
real project and save them in the View Map, following `docs/3D_SCENES.md`. They call the
official JSON API and the `ArchicadMcpAberto` add-on commands directly (`Get3DCamera`,
`Set3DCamera`, `Get3DWindowImage`, `Save3DView`, `Get3DCutPlanes`, `Set3DCutPlanes`,
`Show3DAll`), so they are also the reference for a future `create_3d_scenes` MCP tool.

Needs Python 3.11+, `matplotlib` and `Pillow`. Set `ARCHICAD_PORT` when the project is
not on 19723.

## Workflow

1. `python read_model.py out` reads the zones and the element boxes and draws
   `out/plan.png`. Plan from it: room boxes, walls, columns and furniture.
2. Shoot one top view first (see `shoot.py`) to see the site, the parking and which
   facade is the front one. Boxes alone hid an L-shaped room and an outdoor parking zone.
3. Write `shots.json` with every camera (rules in `docs/3D_SCENES.md`) and run
   `python shoot.py shots.json out sheet1`. Look at `out/sheet1.jpg`.
4. Keep the good ones, retry the bad ones once (`shots2.json`), drop the rest. Skip
   empty rooms and rooms where both tries fail.
5. Axonometrics: a parallel camera, `Show3DAll`, then the same view with a horizontal cut
   1.50 m above each floor.
6. Put the kept shots in `views.json` and save ONE first: save it, move the camera
   elsewhere, ask the user to open the view. Then save the rest with
   `python save_views.py views.json <full View Map path>`. The script restores the 3D
   camera and the cut it found.
7. Show the user a contact sheet with the view names. Never save the project.

`shots.example.json` and `views.example.json` show the formats.

## Live test, 22/10/2026

Archicad 30 build 3001 BRA, Windows, add-on from 07210e2, no Tapir; a 1,800 m^2
single-storey gym project, only camera, cut and new views changed, project not saved.
40 images, 18 views saved in 9 folders.

- `Set3DCamera` / `Get3DCamera`: view cone in radians correct (60 deg = 1.047).
  `twoPointPerspective` keeps its previous value when left out: always send it.
- `Get3DWindowImage`: 40 PNGs of 1619x865, no failure.
- `Save3DView`: the view keeps the camera (opened by the user after the camera moved).
  `folderPath` starts at the View Map's top level: when the scenes folder is inside a
  template folder, `["02 | MODELO 3D", ...]` fails with "Failed to find or create the
  View Map folder" and the template folder must lead the path. New items go to the top
  of their folder, so a folder lists them in reverse order.
- `Get3DCutPlanes` / `Set3DCutPlanes`: a horizontal cut is `pa 0, pb 0, pc 1,
  pd = height`, `cutStatus 8`. `Set3DCutPlanes {"enabled": false}` changed `cutPen`
  from 0 to 1, and setting `cutPen 0` back did not stick. Whether a saved axonometric
  keeps its cut is still to be checked in Archicad.
- `Show3DAll {"fitInWindow": true}`: fine.
- Planning from boxes plus one look per camera took about 33 shots for 18 kept views.
