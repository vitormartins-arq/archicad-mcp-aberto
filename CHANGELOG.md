# Changelog

## Unreleased

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
