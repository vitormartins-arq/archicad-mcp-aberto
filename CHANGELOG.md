# Changelog

## Unreleased

- Add `create_objects`: up to 20 library part objects by exact name, plan position, story,
  absolute base level and angle (radians), through Tapir `CreateObjects`. Size stays the
  library part's default. A name Archicad cannot find fails only that object. Applying
  checks type, story, 3D origin, angle (on the circle) and library part name. Same token,
  port, receipts and timeout as the other writes. Fake shape from the Tapir source, not live.

- Add `set_property_values`: up to 100 scalar property values (string, boolean, integer,
  number, length, area, volume, angle) through the official `SetPropertyValuesOfElements`.
  The preview reads the current value and refuses read-only, unavailable or non-scalar
  properties and wrong value types; applying reads every value back. Same token, port,
  receipts and timeout as the other writes. Fake shape from the JSON API docs, not live.

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
