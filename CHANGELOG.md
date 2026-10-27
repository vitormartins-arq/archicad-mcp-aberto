# Changelog

## Unreleased

- Add native `save_project_as`, `save_next_project_revision` and read-only
  `inspect_project_save`. Preview binds native session/project epoch/stamp and paths;
  saves the in-memory PLN, verifies path/file, then archives the previous revision in
  `Anteriores`. Existing files are refused, archive collisions preserved, unknown saves
  never retried. Requires rebuilt companion add-on; offline tested, native build/live
  validation pending. See `docs/PROJECT_SAVE_REVISIONS.md` for API limitations and recovery.

- Add `list_grid_elements` and `create_grid_elements` (`tools/grids.py`): grid lines
  (Grid Tool elements) through our add-on, which now carries `GetGridElementDefaults`,
  `GetGridElements` and `CreateGridElements` ported from Tapir (added there after 1.7.2,
  MIT). The preview checks GDL parameter names and value types against the tool
  defaults; the batch is one Undo step and every line is read back. Not tested live yet.

- Add `update_favorites_from_elements`: overwrite existing favorites from elements by
  Tapir 1.7.0 `UpdateFavoritesFromElements`. The receipt stays unverified, because
  Tapir cannot read a favorite's settings. Not tested live yet.

- Add `move_navigator_items` (`tools/navigator_moves.py`): move View Map and Layout Book
  items into other folders by Tapir 1.7.0 `MoveNavigatorItem`, read back in the tree.
  Not tested live yet.

- Add `create_surfaces` (`tools/surfaces.py`): new surfaces copied from an existing one
  by Tapir 1.7.0 `CreateSurfaces`, with colour, transparency, type or no texture;
  read back by `GetSurfaces`. Not tested live yet.

- Add `update_drawings` (`tools/drawings.py`): update every Drawing on layouts by Tapir
  1.7.0 `UpdateDrawings`. Tapir answers only success, so the receipt stays unverified.
  Not tested live yet.

- Add `create_classification_systems` (`tools/classification_systems.py`): new systems
  with item trees by Tapir 1.7.0 `CreateClassificationSystems`, read back by
  `GetAllClassificationSystems` and the whole tree. Not tested live yet.

- Add `modify_lamps`: origin, level, size (height through ZZYZX) and `lightIsOn` of
  lamps by Tapir 1.7.0 `ModifyLamps`, the same code as `ModifyObjects`; read back like
  `modify_objects`. The light colour is left out: the Tapir source says Archicad
  discards it. Not tested live yet.

- Add `remove_solid_operations` and `remove_trims` (`tools/solids.py`): remove solid
  element operation links and roof or shell trims by Tapir 1.7.0
  `RemoveSolidElementLinks` and `RemoveElementTrims`, read back as gone. Not tested
  live yet.

- Add `place_hotlinks` (`tools/hotlinks.py`): hotlink modules from .mod or .pln files by
  Tapir 1.7.0 `CreateHotlinkNodes` and `CreateHotlinkInstances`, read back by type,
  story and `GetHotlinks`. Not tested live yet.

- Add `create_layout_subsets` (`tools/layout_book.py`): Layout Book subsets by Tapir
  1.7.0 `CreateLayoutSubset`, read back under their parent. `create_layouts` takes an
  optional `subset`. Not tested live yet.

- Add `create_solid_operations` and `trim_to_roof` (`tools/solids.py`): solid element
  operation links and trims to a roof or shell by Tapir 1.7.0, read back by
  `GetSolidElementLinks` and `GetElementTrims`. Not tested live yet.

- Add `move_to_design_options`: elements into a design option or back to the main model
  by Tapir 1.7.0 `MoveElementsToDesignOptions`, read back per element. Not tested live
  yet.

- Add `create_design_options` (`tools/design_option_create.py`): new design option sets,
  options and combinations in one call (Tapir 1.7.0, Archicad 29+), read back by the
  three inventories. Not tested live yet.

- Add `add_stories` (`tools/stories.py`): new stories above the top or below the bottom
  by Tapir 1.7.0 `SetStories`, sending the existing stories back unchanged; read back by
  `GetStories`. Not tested live yet.

- Add `create_drawings` (`tools/drawings.py`): views on existing layouts by Tapir 1.7.0
  `CreateDrawings`, by View Map name or Navigator GUID, read back on the layout's
  database. Not tested live yet.

- Add `create_composites` (`tools/composites.py`): new composites by Tapir 1.7.0
  `CreateComposites`, skins by building material name, thickness, type and pen, one
  separator line type and pen. Existing names, unknown materials and line types are
  refused in the preview; the read-back compares every skin and separator. Not tested
  live yet.
- Reject invalid `ARCHICAD_MCP_PORTS` entries before discovery: out-of-range TCP
  ports, malformed entries and descending ranges now raise a configuration error.
  Validate endpoints before expanding ranges so a typo such as `1-1000000000`
  cannot allocate a huge list. Custom valid ports, ordering, deduplication and the
  default port range are preserved. Offline tests only.

- `find_elements` resolves its target once per search instead of probing it again
  for every property batch. A search reading properties of 205 elements now makes
  one `GetProductInfo` request to the target instead of four. Property validation,
  batches of 100, pagination and per-element errors are unchanged. Tested offline
  against the fake Archicad; not tested in a real Archicad.

- `read_scene_model` suggests better cameras, after the live run of 22/10/2026 where
  about one suggestion in three was usable. Cameras now stand clear of walls, columns
  and smaller rooms inside the room's box, and their sight line avoids wall and column
  boxes at eye height. Service rooms (DML, depósito, almoxarifado, shaft) are skipped.
  Each room gets a unique label: rooms with the same name get the zone number, and the
  suggested shots carry ready scene names and folders. `Get3DWindowImage` and
  `Save3DView` wait up to 60 s, because a big model took over 12 s live.

- Add 3D scene tools (`tools/scenes.py`) on this project's own add-on (`addon/`):
  `read_scene_model` (rooms, element boxes and suggested cameras, official API only),
  `shoot_3d_scenes` (sets cameras and 3D cuts, returns the images, puts the 3D window
  back) and `save_3d_scenes` (View Map views, one folder per room, preview and one-use
  token). New `ArchicadClient.own_addon` and `AddOnError`. The add-on commands were tested
  live on Archicad 30 build 3001 BRA (22/10/2026, 18 views); the MCP tools themselves are
  not tested live yet.

- Add `create_stairs` (`tools/stairs.py`): straight stairs by Tapir 1.7.0
  `CreateStairs`, with `favorite`, read back by type, story and 3D box. Not tested live
  yet.

- Fix `create_walls` with `favorite`: Tapir 1.7.0 `CreateWalls` requires height and
  thickness even with a favorite, so a wall with only a favorite was refused live
  (Archicad 30 build 3001 BRA, 21/10/2026). Height and thickness are required again,
  and the read-back expects the Basic structure and unlinked top that Tapir 1.7.0 sets
  over the favorite. New `composite` field: a wall Composite by name, whose skins set
  the thickness, so a composite favorite's walls can keep their composite.

- Add `create_zone_categories` (`tools/zone_categories.py`): new zone categories with
  name, code and colour by Tapir 1.7.0 `CreateZoneCategories`, never overwriting an
  existing one, read back with `GetZoneCategories`. Not tested live yet.

- Add `create_lamps`: up to 20 Lamp library parts by name, like `create_objects`, by
  Tapir 1.7.0 `CreateLamps`, with `favorite`. Not tested live yet.

- Add `create_associative_dimensions` to `tools/wall_dimensions.py`: linear dimensions
  between wall ends, linked to the walls, by Tapir 1.7.0 `CreateAssociativeDimensions`,
  read back witness point by witness point with `GetDimensionData`. Not tested live yet.

- Add `modify_morphs` to `tools/modify.py`: box size (box morphs only, corner kept),
  building material and surface by name, and shadows, by Tapir 1.7.0 `ModifyMorphs`,
  each read back. Not tested live yet.

- Add `create_keynote_labels` to `tools/labels.py`: up to 20 labels showing a keynote
  item's fields as autotext, by Tapir 1.7.0 `CreateKeynoteLabels`. The preview refuses
  an item that is not in the keynote tree; the read-back checks type, class and
  position and reports the story and text. Not tested live yet.

- `create_objects` takes an optional `favorite` too. Tapir still needs
  `libraryPartName` and cannot tell which part a favorite holds, so the preview notes
  that the favorite's own part must be given. The angle comes from the favorite unless
  given. Not tested live yet.

- `create_walls`, `create_slabs`, `create_columns` and `create_beams` take an optional
  `favorite` (Tapir 1.7.0 `favoriteName`): the favorite is applied to the tool first,
  the given fields override it, and the size and structure it holds may be left out.
  The preview checks the favorite exists for that element type. Zones, texts, labels,
  meshes and the 2D drafting tools take `favorite` too. Not tested live yet.

- Add `create_hotspots` to `tools/drafting.py`: up to 50 2D hotspots by Tapir 1.7.0
  `CreateHotspots`, with position, optional height, layer and pen. Read back by type,
  story, layer, position, height and pen. Not tested live yet.

- Add `create_splines` to `tools/drafting.py`: up to 50 auto-smoothed 2D splines by
  Tapir 1.7.0 `CreateSplines`, through 3 to 500 points in metres, open or closed, with
  optional layer and pen. Read back by type, story, layer, pen, `closed` and points
  within 1 mm. Not tested live yet.

- Add `create_openings` (new `tools/voids.py`): up to 50 rectangular Opening-tool
  openings by Tapir 1.7.0 `CreateOpenings` in existing editable walls or slabs, from a
  base point in absolute project metres (z is the bottom edge) and a positive width and
  height. Read back as an Opening that the host lists among its connected openings.
  Tested live on AC30 build 3001 BRA with Tapir 1.7.0 in a straight wall, a 45-degree
  wall and a slab (all verified).

- Add `create_wall_thickness_dimensions` (new `tools/wall_dimensions.py`): up to 50
  associative dimensions of both faces of existing editable walls by Tapir 1.7.0
  `CreateWallThicknessDimensions`, one per wall, on the wall's story. By default the
  dimension line crosses the middle of a straight wall, perpendicular to it; a reference
  point and direction can be given, and a curved wall needs the direction. Read back as a
  Dimension on the wall's story. Tested live on AC30 build 3001 BRA (verified).

- Add `create_morphs` (new `tools/morphs.py`): up to 50 axis-aligned box morphs by
  Tapir 1.7.0 `CreateMorphs`, each from a base corner in absolute project metres, a
  positive size and an explicit story. Material and display take the Morph defaults. The
  read-back checks type, story, origin, axes and a closed Solid body, then the 3D
  bounding box. The box is sent as an explicit closed `body`: live on AC30 build 3001 BRA
  with Tapir 1.7.0, the `size` box came out as an open Surface with five faces. The
  preview warns that a morph on a story Archicad is not showing opens a dialog that
  blocks the API.

- Add keynotes (new `tools/keynotes.py`, Archicad 28 or newer): `list_keynotes` reads the
  tree (Tapir 1.7.0 `GetKeynoteTree`) as folders and items with GUIDs and key paths;
  `create_keynote_folders` and `create_keynote_items` only add (`CreateKeynoteFolders`,
  `CreateKeynoteItems`), refuse a key that already exists anywhere in the tree, and read
  each new entry back by GUID. Tested live on AC30 build 3001 BRA (verified; a repeated
  key is refused).

- Add three read-only Design Options tools from the pinned Tapir 1.7.0 source:
  `list_design_options` returns sets, options and combinations;
  `get_elements_of_design_options` resolves option members; and
  `get_design_options_for_elements` distinguishes linked options, the main model,
  missing options and nonexistent elements. Inputs are bounded, GUIDs and response
  identity are validated, and native per-option errors are preserved. These detailed
  reads require Archicad 29+. The fixture is source-derived and explicitly not live.

- Add `create_interior_elevations` (new `tools/interior_elevations.py`): up to 20
  interior elevations by Tapir 1.7.0 `CreateInteriorElevations`, each from a chain of 2
  to 50 points (one segment per pair, `closed` repeats the first point), with an optional
  reference ID, read back on the story and in the Project Map. The Project Map check is
  shared with `create_sections`. Not yet tested live.

- Add `set_attribute_property_values` (new `tools/attribute_properties.py`): up to 100
  custom property values on attributes (building materials, composites, profiles and
  others) by Tapir 1.7.0 `SetPropertyValuesOfAttributes`. Values travel as display text,
  as Tapir reads and writes them; the preview shows the current text and refuses
  read-only, unknown or unavailable properties, and each value is read back as text.
  Not yet tested live.

- Add `create_favorites_from_elements` (in `tools/favorites.py`): up to 50 new favorites,
  each captured from one existing element by Tapir 1.7.0 `CreateFavoritesFromElements`
  (settings, classifications, editable property values), optionally in a Favorites
  palette folder. A name that already exists for that element type is refused, so no
  favorite is ever overwritten; each new name is read back with `GetFavoritesByType`.
  Not yet tested live.

- Add `create_sections` (new `tools/sections.py`): up to 20 straight sections by
  Tapir 1.7.0 `CreateSections`, with preview, single-use token, receipts, and a read-back
  on the story (CutPlane) and in the Project Map (SectionItem by its new name). Not yet
  tested live.

- `rename_items` after its live test (14/10/2026, Archicad 30 build 3001 BRA, Tapir
  1.7.0): surfaces are refused, because `CreateSurfaces` with only the name also changed
  the texture; layer combinations send the empty `layers` list that
  `CreateLayerCombinations` requires (the schema check refused every rename before); a
  call Archicad refuses outright is reported as `failed`, not `unknown`.

- Add `rename_items` (new `tools/renames.py`) to clean up a template quickly: rename
  Navigator items (View Map, Project Map, Layout Book), favorites, classification systems
  and items, custom property groups and properties, building materials,
  layers, layer combinations (each layer's state is read back unchanged) and attribute
  folders (official `API.RenameAttributeFolders`, e.g. the layer folders) by find and replace or by exact old -> new names, with preview, single-use
  token, receipts and a read-back of every name. Items keep their GUID. Clashing and
  blank names are refused. The fake's shapes come from the Tapir 1.7.0 source, not a
  live capture. Not yet tested live.

- Fix what the live test of 14/10/2026 found (Archicad 30 build 3001 BRA, Tapir 1.7.0;
  results in `docs/VALIDAR-resultado-2026-10-14.md`):
  - `modify_objects` sets the height through the `ZZYZX` GDL parameter and reads it
    back, because Tapir changes only x and y and reads `dimensions.z` as 0. A part
    without `ZZYZX` is refused in the preview.
  - Polylines and fills are checked by the coordinates in their details instead of
    `Get2DBoundingBoxes`, which answers error 7203 for them; a circle that reads back as
    a full Arc counts as a circle.
  - `apply_favorites` and `favorite_name` find favorites that start with a space, such
    as " Parede Genérica - Default".
  - `create_properties` takes classification items by id or name in `available_for`,
    not only by GUID.
  - `set_project_info_fields` refuses `CLIENT_FULLNAME`, which Archicad keeps empty, and
    points to the given and family name fields.

- Add worksheets, details and layouts (new `tools/documents.py`): `create_worksheets`,
  `create_details` and `create_layouts` through Tapir 1.7.0 `CreateWorksheets`,
  `CreateDetails` and `CreateLayout`. Layouts go on an existing master layout by its
  Navigator ID, so a missing master is refused instead of being created. Each new
  database is found back in the Navigator. The fake's shapes come from the Tapir source,
  not a live capture. Not yet tested live.

- Add custom property groups and properties (new `tools/property_definitions.py`):
  `list_property_groups`, `create_property_groups` and `create_properties` through Tapir
  1.7.0 `GetAllProperties`, `CreatePropertyGroups` and `CreatePropertyDefinitions`.
  Every Tapir property type is supported, with defaults, enum options and availability by
  classification item or whole system; existing names and built-in groups are refused,
  and each result is read back. The fake's shapes come from the Tapir source, not a live
  capture. Not yet tested live.

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

- Add `modify_labels`: safe Text label content and paper font-height edits through Tapir
  1.7.0 `ModifyLabels`, with read-back and source-derived simulated coverage. Coordinates
  and story changes are unsupported by that native command and refused. Not tested live.

- Add issue management: `list_issues`, `create_issues` and `attach_elements_to_issue`
  through source-confirmed Tapir 1.7.0 commands. Highlight associations only, missing
  elements refused, shared confirmation/receipts and per-item read-back. Singular native
  commands stop on an unknown outcome; each is a separate Undo step. Simulated only.

- Add read-only `get_navigator_tree`: flattened project/view/layout/publisher tree with
  GUID, parent and depth, filtering and pagination. Exact native map values; PublisherSets
  selects a named set or explicitly notes the native first-set default. Source-derived
  Tapir 1.7.0 fixture, not a live capture; preserves the existing document fake.

- Add `create_meshes` and limited `modify_meshes` using Tapir 1.7.0 `CreateMeshes` and
  `ModifyMeshes`: simple 3D terrain boundaries, absolute public heights, explicit skirts
  and ridge display, existing write protections and read-back. No holes/arcs/contour edits;
  complex existing meshes are refused. Source-derived fixtures, simulation only.

- Add `get_view_settings` and limited `set_view_settings`: scale denominator and existing
  layer combination of up to 100 PublicViewMap views. Shared preview/token/port/receipts,
  per-view errors, settings read-back and unchanged combination-state verification. Native
  Navigator changes have no guaranteed Undo; receipts retain old values and say so. Other
  write tools retain their existing note. Source-derived fixtures, simulated only.

- Fix geometry verification at large/georeferenced coordinates: disable relative
  tolerance in geometric field/polygon matching and moved-box verification. An ignored
  5 mm move or a wrong vertex could previously read as verified near coordinate 6500000;
  a valid small unclosed polygon could also be mistaken for closed. Regression cases
  reproduce the failures at positive/negative origins using only the simulator.

- Add `list_layer_combinations` (optional saved per-layer states, filtered/paginated
  before batched reads) and `set_layer_settings` for current flags/group of existing
  layers by name/GUID. Protected first layer and duplicate aliases refused; unchanged
  name/identity/flags read back. No guaranteed attribute Undo; unexpected returned GUID
  is unknown, including the native overwrite base creating a vanished target. Simulated only.
- 2026-10-15, T23 investigation: native Tapir 1.7.0 does not support custom Project
  Info field creation on AC30 and filters generated IDs from its field reader.
  Documented the upstream prerequisite; no unverified creation tool added.

- Add `add_comment_to_issue`: 1–20 comments on existing issues with optional author,
  shared preview/token/port/receipts, comment GUID/read-back and preserved prior comments.
  Stops remaining writes after an unknown outcome; source-derived simulation only.

- Add `create_view_map_folders` and `clone_to_view_map`, with existing parent/source
  GUID preflight, bound trees, per-item native commands and independent tree verification.
  No guaranteed Navigator Undo; never moves, deletes, saves or publishes. Simulated only.

- Add `create_classification_items` with existing-system/parent GUID checks, duplicate
  ID refusal and independent item/tree read-back. Handles native empty success result
  arrays by sending one item per call; no success is inferred without read-back.
  Shared preview/token/port/receipts, no deletion or saving. Simulated only.

- Reconfirm the bound project context between sequential classification creation
  commands and stop remaining items before dispatch after a project switch.
  A classification tree read-back mismatch also stops the remaining batch.
  Re-read the selected system and tree immediately before each later command.

- Harden T25 clone verification: preserve and verify the native source GUID and
  inheritance flags; reject Project Map containers instead of previewing them as one
  viewpoint. Refuse embedded NUL and folder names exceeding 255 UTF-16 units.
  Regressions reproduce previously verified clones with missing/wrong source identity.

- Reconfirm the project context between sequential folder/clone commands and stop
  remaining Navigator writes before dispatch after a project switch.
  A tree read-back mismatch also stops the remaining batch before another write.
  Re-read bound Navigator trees immediately before each later command.

- Reconfirm the bound project context between sequential comment writes, stopping all
  remaining items before dispatch if the selected project changes during the batch.
  A comment read-back mismatch also stops the remaining batch before another write.
  Re-read the next issue and its comments immediately before dispatch to catch concurrent edits.

### Live corrections — 2026-10-15
- Refuse the synthetic PublicViewMap root as a folder/clone insertion parent during preview.
  Use the actual project folder or a subfolder. Add AC30 build 3001 BRA live headers/error
  and regressions, preserving explicit-port and per-item receipt checks.


### Live corrections — 2026-10-15
- Explain Section marker/default recovery on APIERR_BADID without changing defaults or retrying.
- Verify equivalent scalar numeric attribute values despite decimal padding; retain raw text
  and strict checks for other types/formats. Add an AC30 build 3001 BRA live capture.
