# 3D scenes: how to place cameras like an architectural photographer

Guide for the model when it is asked to "generate nice 3D views" of a project and save
them in the View Map. It uses the add-on commands in `addon/` (`Set3DCamera`,
`Get3DWindowImage`, `Save3DView`, `Get3DCutPlanes`, `Set3DCutPlanes`). Lengths in
metres, angles in radians at the MCP side.

## Workflow

1. Read the zones (name, number, story, polygon) and the walls, columns and furniture of
   each story, so cameras are planned from the model, not by trial and error.
2. Plan every camera first, in one pass, with the rules below.
3. For each camera: `Set3DCamera`, `Get3DWindowImage`, look at the image. Keep it, move
   it once (step back, shift sideways, turn a little) or drop it. Never more than two
   tries per camera: an hour of trial and error is worse than a few good shots.
4. Save the kept ones with `Save3DView` into one folder per room.
5. Show the user a contact sheet (all images with their view names) before they save
   the project. Never save the project.

## Interior photographs

Architectural interior photography is mostly **one-point perspective**:

- The camera faces the main wall of the room square on: the line of sight is
  perpendicular to that wall.
- The camera is level: `camera.z == target.z`. Vertical lines stay vertical. Never tilt
  up or down to fit the ceiling; step back or widen the lens instead.
- Height 1.20 to 1.40 m above the finished floor (lower than eye level reads better for
  furniture and keeps the ceiling from dominating). 1.60 m for circulation and tall
  spaces when the floor is the subject.
- Stand against the opposite wall or in the doorway, slightly off the room's axis
  (around one third of the width) so the composition is not dead symmetric, unless the
  room itself is symmetric and that is the point.
- View cone 50 to 65 degrees. Wider than 75 distorts the edges; use it only for small
  rooms where nothing else fits.
- Nothing within about 1 m of the lens: no column, door leaf or chair cut by the frame
  edge in the foreground.

**Two-point perspective**, the minority of shots (about one per room, more in big halls):

- From a corner, looking across the room, still level (`camera.z == target.z`).
- Turned so one wall takes about two thirds of the frame and the other one third,
  not split 50/50 down the corner.

Skip rooms where no good picture exists (storage, shafts, rooms smaller than about
6 m^2, rooms still empty in the model) and say which were skipped and why.

## Exterior

- Eye-level two-point views from the street or the parking, 1.60 m, 30 to 45 degrees to
  the main facade, level.
- One frontal one-point view of each main facade when it is worth it.

## Isometrics

- One general axonometric of the whole building from the most informative corner.
- One cut axonometric per story to see inside: a horizontal 3D cutting plane about
  1.50 m above that story's floor (`Set3DCutPlanes`), same angle as the general one.
  A horizontal cut at height h is the plane `{"cutStatus": 8, "pa": 0, "pb": 0, "pc": 1,
  "pd": h}` (read live on Archicad 30). Turn the cut off before the next perspective.

## Names and folders

- One folder per room under a scenes folder, e.g.
  `["02 | MODELO 3D", "AMBIENTES", "04 PESO LIVRE E ARTICULADO"]`.
- View names: `<room> - 1P 01`, `<room> - 2P 01` (one or two vanishing points);
  `ISOMETRICA GERAL`, `ISOMETRICA <story>`; `EXTERNA - <place> 01`.
- Use the zone's own spelling for the room name.
