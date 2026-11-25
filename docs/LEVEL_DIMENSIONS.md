# Native level dimensions

`create_level_dimensions` creates real Archicad **LevelDimension** elements associated
with a slab, not Symbol Labels. Requires the companion's `PreviewLevelDimensions`,
`CreateLevelDimensions` and `GetLevelDimensions` commands. It never saves or deletes.

Input is `dimensions` (1..20), each with `slab_guid`, `position: {x, y}` in metres,
optional `layer_index` and exact `favorite` (must be LevelDimension). Dry run is the
default; apply requires the explicit port and its single-use confirmation token.
The measurement point stays at the supplied position. A preview recheck rejects a
changed slab elevation, target, settings or inputs. A batch uses one Undo step.

Initial scope: top-reference slabs, straight contours with holes, one measured note,
project-zero elevation. The point must be inside the contour and outside all holes.
Other slab reference planes, curved contours, dual-note favorites/defaults and hidden
or locked destination layers are refused. This scope does not emulate two finished/
structural values with a Label or custom text.

Each item has its own receipt/error. A separate native getter checks type, slab GUID,
parent type, story, physical position, non-static association, measured note, project-zero
origin, numeric level and graphical settings. A failed getter remains unverified; lost
write responses stay unknown and are not retried. `verified` is numeric readback,
not visual acceptance. Inspect the actual marker/text and slab context before completion.

The companion code uses SDK `API_LevelDimensionType`, `ACAPI_Element_GetDefaults`,
`ACAPI_Favorite_Get`, `ACAPI_Element_GetMemo`, `ACAPI_Element_CalcBounds`,
`ACAPI_Element_Create` and `ACAPI_Element_Get`. This is our command contract, not a
Tapir command. Fixtures and tests are source-derived/synthetic, **not live captures**.
Real Archicad acceptance must still confirm that the annotation follows later slab
height edits and shows the expected formatted measured value. No model was changed
while developing this feature.
