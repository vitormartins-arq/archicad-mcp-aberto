# Changelog

## Unreleased

- Add locking and Update Zones (new `tools/locks.py` and `tools/zones.py`):
  `lock_elements`, `unlock_elements` and `update_zones` through Tapir 1.7.0
  `LockElements`, `UnlockElements` and `UpdateZones`. Lock and unlock read every
  element's editability back with `FilterElements`; unlock refuses elements on a locked
  layer. `update_zones` recalculates every zone and stays unverified. The fake's shapes
  come from the Tapir source, not a live capture, and its `FilterElements` now treats
  elements on a locked layer as not editable. Not yet tested live.

- Add Project Info and favorites (new `tools/project_info.py` and `tools/favorites.py`):
  `get_project_info_fields`, `set_project_info_fields`, `list_favorites` and
  `apply_favorites` through Tapir 1.7.0 `GetProjectInfoFields`, `SetProjectInfoField`,
  `GetFavoritesByType` and `ApplyFavoritesToElements`. Fields go by id or visible name and
  are read back; applied favorites stay unverified because Tapir cannot read a favorite's
  settings. The fake's shapes come from the Tapir source, not a live capture. Not yet
  tested live.

- Add selection, highlight and groups (new `tools/selection.py`): `select_elements`,
  `highlight_elements`, `get_element_groups` and `create_groups` through Tapir 1.7.0
  `ChangeSelectionOfElements`, `HighlightElements`, `GetGroupsOfElements`,
  `GetElementsOfGroups` and `CreateGroups`. Selection and highlight do not change the
  model, so they act at once and report what Archicad ended with; `create_groups` uses
  the preview, token, receipts and read-back. The fake's shapes come from the Tapir
  source, not a live capture. Not yet tested live.

- Add layers (new `tools/layers.py`): `list_layers`, `create_layers` and
  `set_element_layers` through Tapir 1.7.0 `GetLayers`, `CreateLayers` and
  `SetDetailsOfElements`. New layers never overwrite an existing name; elements move to a
  layer by name with preview, token, receipts and read-back. The fake now gives each layer
  its own GUID. Its shapes come from the Tapir source, not a live capture. Not yet tested
  live.

- Add 2D drafting (new `tools/drafting.py`): `create_lines`, `create_polylines`,
  `create_arcs`, `create_circles` and `create_fills` through Tapir 1.7.0
  `CreateLineElements`, `CreatePolylines`, `CreateArcs`, `CreateCircles` and
  `CreateHatches`. Layer and fill go by name, the pen by index. Polylines and fills are
  checked by their plan box, because Tapir reports no geometry for them. The fake's shapes
  come from the Tapir source, not a live capture. Not yet tested live.

- `create_roofs` now sends `structureType: Basic`. Live on 13/10/2026 (Archicad 30 build
  3001 BRA, Tapir 1.7.0) a Composite Roof tool default kept its own 0.30 m when 0.25 m
  was asked, so all three roofs ended `verification_failed`.

- Add `list_classifications` and `set_classifications` (new `tools/classifications.py`):
  read the classification systems and one system's item tree, and classify or unclassify
  up to 100 elements through the official `SetClassificationsOfElements`, with preview,
  token, receipts and read-back through `GetClassificationsOfElements`. Systems and items
  can be named; ambiguous names are refused. Add `create_labels` (new `tools/labels.py`,
  Tapir `CreateLabels`): up to 20 text labels, attached to an element or free. The fake's
  shapes come from the official package and the Tapir 1.7.0 source, not a live capture.
  Not yet tested live.

- Add `modify_roofs` (Tapir `ModifyRoofs`, multi-plane roofs only: thickness, level from
  its story, eaves overhang, levels) and `modify_texts` (Tapir `ModifyTexts`: content,
  position on the same story, angle, height in paper millimetres, justification), in
  `tools/modify.py` with the same preview, token, receipts and read-back. The read-back now
  compares angles on the circle, text in LF form and lists item by item. Not yet tested
  live.

- Add `create_roofs` (Tapir `CreateRoofs`): up to 20 single-plane roofs (pivot line and
  slope) or multi-plane roofs (polygon as pivot polygon, optional levels and eaves
  overhang), absolute level as in `create_slabs`. Add `create_texts` (Tapir
  `CreateTexts`): up to 20 plain texts with position, story, angle and optional height in
  paper millimetres and justification. Both verify what Archicad stored. The fake's
  shapes come from the Tapir 1.7.0 source, not a live capture. Not yet tested live.

- Add `modify_slabs`, `modify_columns`, `modify_beams`, `modify_windows`, `modify_doors`
  and `modify_objects` (new `tools/modify.py`), following `modify_walls`: dry run, token,
  explicit port, per-element receipts and read-back of every requested field. They use
  Tapir 1.7.0 `ModifySlabs`, `ModifyColumns`, `ModifyBeams`, `ModifyWindows`,
  `ModifyDoors` and `ModifyObjects`. Levels are offsets from the element's story; a slab
  or object level that Tapir would place on another story is refused. The fake's Modify*
  results come from the Tapir source, not a live capture. Not yet tested live; the steps
  are in `docs/VALIDAR.md`.

- `rotate_elements` receipts add `normalized_angles` when Archicad stores an angle outside
  [0, 2π), as the 2π seen live after rotating an object back. Nothing is written again.

- Add `run_read_command`: one read-only command from a closed list (61 official JSON API
  commands from the `archicad` 30.3000 package, 85 Tapir 1.7.0 commands from its
  `AddOnMain.cpp`), named `API.<Command>` or `Tapir.<Command>`, parameters sent unchanged
  and the response returned raw. Anything not written out in the list is refused before it
  reaches Archicad. The list lives in `docs/GATEWAY.md`, kept in step by a unit test.

- Add `create_windows` and `create_doors`: up to 20 openings each in existing straight walls,
  through Tapir `CreateWindows`/`CreateDoors`, with wall GUID, offset along the wall, and
  optional size, sill and favorite name. Tapir 1.7.0 has no library part name input for
  these, so the tool default or the favorite decides the part and the receipt reports it.
  Verifies type, story, owner wall, offset and the given size and sill. Tested live on
  Archicad 30 build 3001 BRA with Tapir 1.7.0; the fake copies the live Window/Door details.
  Favorite names are kept exactly, since live favorites can start with a space.

- Credit Vitor Martins as the project's creator in LICENSE, README, LEIA-ME, pyproject and
  the .mcpb manifest. The license stays MIT.

- Add `create_objects`: up to 20 library part objects by exact name, plan position, story,
  absolute base level and angle (radians), through Tapir `CreateObjects`. Size stays the
  library part's default. A name Archicad cannot find fails only that object. Applying
  checks type, story, 3D origin, angle (on the circle) and library part name. Same token,
  port, receipts and timeout as the other writes. Tested live on Archicad 30 build 3001 BRA
  with Tapir 1.7.0, including the not-found error the fake now copies.

- Add `set_property_values`: up to 100 scalar property values (string, boolean, integer,
  number, length, area, volume, angle) through the official `SetPropertyValuesOfElements`.
  The preview reads the current value and refuses read-only, unavailable or non-scalar
  properties and wrong value types; applying reads every value back. Same token, port,
  receipts and timeout as the other writes. Tested live on Archicad 30 build 3001 BRA with
  Tapir 1.7.0. The live test caught that `GetDetailsOfProperties` puts the GUID under
  `propertyId.guid`; the fake had a `guid` key, which hid a missing name in the preview and
  a read-only check that never fired.

- Add `move_elements`: up to 50 elements, each by its own vector in metres, through
  Tapir `MoveElements` without copying. The preview refuses unknown, hotlinked or box-less
  elements and records their 2D/3D boxes; applying checks every box moved by its vector
  (1 mm). Same single-use token, explicit port, receipts and timeout as the create tools.
  Response shape `{"executionResults":[{"success":true}]}` confirmed live on Archicad 30
  build 3001 BRA with Tapir 1.7.0 (untitled project, 11/10/2026).

- Package for Claude Desktop: `manifest.json` (MCPB 0.4, uv runtime) and `.mcpbignore`;
  a tag `v*` workflow runs the tests and drafts a release with wheel, sdist and `.mcpb`.
  README covers the bundle, `uvx` from GitHub and Codex. A test keeps the manifest tool
  list and version in step with the server.

- Add read-only `get_bounding_boxes`: official JSON API 2D/3D boxes in metres for
  1 to 500 GUIDs, ordered per-element results/errors, no Tapir requirement and
  ambiguous-target refusal. Documentation-derived fixture and simulated tests only.

- Add `create_columns` for straight rectangular/circular columns, absolute base level,
  shared single-use confirmation/receipts/write timeout and per-column verification.
  Add captured column detail fixtures, simulated tests, target-safety coverage and a smoke column.
  Match Archicad circular-section dimension linkage during creation and verification.

- Writes and their verification wait up to 120 s (`ARCHICAD_MCP_WRITE_TIMEOUT`).
  A live `CreateSlabs` on an upper story took over 12 s and was reported as unknown.
- Add `create_slabs`: simple polygons, absolute project level, dry-run default,
  single-use confirmation, per-slab receipts/errors and geometry verification.
  Tapir 1.7.0 fixture derived from documentation/source; simulated tests only.

- Add `create_walls`: dry-run by default, single-use reviewed plans, local per-wall
  receipts, native per-element errors and geometry verification after creation.
  This initial scope covers straight Basic walls and is tested against the simulated Archicad.
- `get_element_details` returns `floorPlanPolygons: []` and a note when Tapir finds no cut
  fill for an element, instead of silently leaving the key out.

- Fix: `list_properties` always returned an empty list. Archicad returns the IDs under
  `propertyIds`, not `properties` (found in the first live test, Archicad 30 build 3001).

- Phase 0: connection with one reused HTTP client, discovery of several instances with
  project name and Tapir state, nine read-only tools, simulated Archicad and CI.

- Deduplicate repeated floor-plan polygons within each element and report the removed count.

- Add read-only `find_elements` with staged filters, pagination, scalar comparisons and 100-element read batches.

- Add guarded `delete_elements` for untitled test projects using documented Tapir commands, with editability checks, single-use confirmation and absence verification.

- Add story/layer display names to existing-element previews without binding mutable names into confirmation identity.

- Add safe `create_beams` with rectangular section, absolute level and post-write geometry verification.

- Add safe `create_zones` with shared slab polygon validation and per-zone contour/name/number verification.
  Tapir 1.7.0 omits `polygonArcs` for an outline without arcs, so zone verification accepts
  the missing key (found in review against the Tapir source; the fake used to send `[]`).

- Add read-only `list_library_parts` and source investigation; preflight object document names against loaded Object parts before issuing a token.

- Let unconfirmed object names in partial library inventories proceed per item to native creation; complete inventories still reject unknown names during preview.
- Refresh README status for all 22 tools, recorded AC30 build 3001 BRA live checks and the nearly complete Phase 1 roadmap.

- Add safe rotate_elements with native per-item errors and coordinate/angle or quarter-turn box verification.

- Add Object GDL parameter reads and safe scalar writes with flag/type checks and read-back verification.

- Add safe limited ModifyWalls edits with shape/editability checks and requested-field verification.
