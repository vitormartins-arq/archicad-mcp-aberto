# archicad-mcp-aberto

Open source [MCP](https://modelcontextprotocol.io) server that lets AI assistants
(Claude, Codex, Cursor and others) work with a running Archicad: read the model and
preview safe model changes with explicit confirmation, per-item receipts and verification.

[Leia em português](docs/LEIA-ME.pt-BR.md)

> Not an official Graphisoft product and not affiliated with Graphisoft or Nemetschek.
> Archicad is a trademark of Graphisoft SE.

## Why

Graphisoft's own MCP server is in beta for Archicad 30 Collaborate and Max only. This
project works with any Archicad that has the JSON API (25 and later) plus the free,
open source [Tapir](https://github.com/ENZYME-APD/tapir-archicad-automation) add-on.

## How it works

```
AI client ──stdio──> archicad-mcp-aberto ──HTTP JSON, localhost 19723–19743──> Archicad
                                                                  ├─ official JSON API
                                                                  └─ Tapir add-on (C++)
```

The server only talks to `localhost`. It sends no telemetry and makes no internet calls.

## Status

Pre-alpha. Phase 1 is nearly complete: **26 tools**, with **14 read-only** tools and
**12 write** tools. Writes preview by default and require a single-use confirmation token
and explicit port to apply. No tool saves the project. Rotation, GDL parameters and
limited straight-wall editing are available, tested only with the simulated Archicad
in this delivery; operator live validation of these additions remains pending.

| Tool | Access | What it does | Needs Tapir |
|---|---|---|---|
| `discover_archicad` | Read | Open instances, ports, project names and counts | for project name |
| `list_elements` | Read | Paged element GUIDs, optionally by type | no |
| `get_selection` | Read | Current selection, without changing it | no |
| `list_properties` | Read | Property definitions | no |
| `get_properties` | Read | Property values, with per-item errors | no |
| `tapir_status` | Read | Add-on availability and version | yes |
| `get_project_info` | Read | Project name/path and Teamwork/untitled state | yes |
| `get_stories` | Read | Story indices, names and levels | yes |
| `get_element_details` | Read | BIM details and optional floor-plan polygons | yes |
| `get_bounding_boxes` | Read | 2D/3D boxes in metres, with per-element errors | no |
| `list_building_materials` | Read | Material GUIDs/indices/names and cut-fill pens | yes |
| `find_elements` | Read | Type/story/layer/property filters and pagination | for details |
| `get_gdl_parameters` | Read | Object GDL values/types/flags, up to 100 GUIDs | yes |
| `run_read_command` | Read | One read-only official or Tapir command from a closed list, raw response | some |
| `list_library_parts` | Read | Loaded part names/GUIDs/types, with partial-inventory diagnostics | yes |
| `list_classifications` | Read | Classification systems, or one system's items as a flat tree | no |
| `get_project_info_fields` | Read | Project Info fields (id, name, value) that title blocks show | yes |
| `list_favorites` | Read | Favorite names for one element type | yes |
| `list_property_groups` | Read | Property groups with custom flag and property count | yes |
| `get_element_groups` | Read | The group holding each element and its members | yes |
| `list_layers` | Read | Layers with hidden, locked, wireframe and intersection group | yes |
| `list_design_options` | Read | Design Option sets, options and combinations | yes; AC29+ |
| `get_elements_of_design_options` | Read | Elements belonging to Design Options, with per-option errors | yes; AC29+ |
| `get_design_options_for_elements` | Read | Design Option status and details for elements | yes; AC29+ |
| `create_walls` | Write | Up to 20 straight walls, Basic or of a composite | yes |
| `create_slabs` | Write | Up to 20 simple polygon slabs | yes |
| `create_columns` | Write | Up to 20 rectangular/circular columns | yes |
| `create_objects` | Write | Up to 20 library objects by name, position and angle | yes |
| `create_lamps` | Write | Up to 20 lamps by library part name, position and angle | yes |
| `create_stairs` | Write | Up to 20 straight stairs along a baseline, with `favorite` | yes |
| `create_zone_categories` | Write | Up to 50 new zone categories with name, code and colour | yes |
| `create_beams` | Write | Up to 20 straight rectangular beams | yes |
| `create_zones` | Write | Up to 20 manually bounded polygon zones | yes |
| `create_roofs` | Write | Up to 20 single- or multi-plane roofs from simple polygons | yes |
| `create_texts` | Write | Up to 20 plain texts on stories | yes |
| `create_labels` | Write | Up to 20 text labels, free or attached to an element | yes |
| `create_lines` | Write | Up to 50 straight 2D lines on a story | yes |
| `create_polylines` | Write | Up to 50 straight-segment 2D polylines | yes |
| `create_splines` | Write | Up to 50 auto-smoothed 2D splines | yes |
| `create_hotspots` | Write | Up to 50 2D hotspots on a story | yes |
| `create_keynote_labels` | Write | Up to 20 labels showing a keynote item's fields | yes |
| `modify_morphs` | Write | Up to 50 morphs: box size, building material, surface, shadows | yes |
| `create_arcs` | Write | Up to 50 circular 2D arcs | yes |
| `create_circles` | Write | Up to 50 full 2D circles | yes |
| `create_fills` | Write | Up to 50 fills (hatches) on simple polygons | yes |
| `select_elements` | View | Replace, add to or remove from the selection | yes |
| `highlight_elements` | View | Highlight elements in one color, or clear it | yes |
| `create_groups` | Write | Up to 20 groups of editable, ungrouped elements | yes |
| `set_project_info_fields` | Write | Up to 30 Project Info values, read back | yes |
| `apply_favorites` | Write | Apply favorites by name to up to 50 elements (settings, never geometry) | yes |
| `lock_elements` | Write | Lock up to 100 editable elements (manual lock, not Teamwork) | yes |
| `unlock_elements` | Write | Unlock up to 100 locked elements not on a locked layer | yes |
| `update_zones` | Write | Update Zones: recalculate every zone of the project | yes |
| `create_property_groups` | Write | Up to 20 empty custom property groups | yes |
| `create_properties` | Write | Up to 50 custom properties with type, default, options and availability | yes |
| `create_worksheets` | Write | Up to 20 empty independent worksheets in the Project Map | yes |
| `create_details` | Write | Up to 20 empty independent details in the Project Map | yes |
| `create_layouts` | Write | Up to 20 layouts on an existing master layout | yes |
| `rename_items` | Write | Rename template items in bulk: Navigator, favorites, classifications, properties, attributes, layer combinations, attribute folders | yes |
| `create_layers` | Write | Up to 50 new layers; existing names are refused | yes |
| `set_element_layers` | Write | Move up to 100 editable elements to existing layers | yes |
| `rotate_elements` | Write | Rotate up to 50 editable elements with geometry checks | yes |
| `set_gdl_parameters` | Write | Edit existing scalar Object GDL values with read-back | yes |
| `modify_walls` | Write | Limited edits of up to 50 straight walls, read back after apply | yes |
| `modify_slabs` | Write | Thickness and level of up to 50 slabs, read back after apply | yes |
| `modify_columns` | Write | Position, base, height and section of up to 50 columns | yes |
| `modify_beams` | Write | Endpoints, level and section of up to 50 straight beams | yes |
| `modify_windows` | Write | Size, sill and position of up to 50 windows in walls | yes |
| `modify_doors` | Write | Size, sill and position of up to 50 doors in walls | yes |
| `modify_objects` | Write | Position, level and dimensions of up to 50 objects | yes |
| `modify_roofs` | Write | Thickness, level, overhang and levels of up to 50 multi-plane roofs | yes |
| `modify_texts` | Write | Content, position, angle, size and justification of up to 50 texts | yes |
| `create_windows` | Write | Up to 20 windows in existing straight walls | yes |
| `create_doors` | Write | Up to 20 doors in existing straight walls | yes |
| `move_elements` | Write | Move up to 50 elements without copying; check displaced boxes | yes |
| `set_property_values` | Write | Up to 100 scalar property changes, read back after apply | no |
| `set_classifications` | Write | Classify (or unclassify) up to 100 elements, read back after apply | yes |
| `delete_elements` | Write | Up to 50 editable elements, only in untitled test projects | yes |
| `modify_labels` | Write | Text and paper text height of up to 50 Text labels; position changes refused | yes |
| `list_issues` | Read | Issue GUIDs, names, tags and native metadata with filtering/pagination | yes |
| `create_issues` | Write | Up to 20 issues with per-issue receipt and name/tag read-back | yes |
| `attach_elements_to_issue` | Write | Associate existing elements as Highlight, verified per element | yes |
| `get_navigator_tree` | Read | Flattened project, view, layout or publisher tree; search and pagination | yes |
| `create_meshes` | Write | Simple 3D terrains from absolute project coordinates, read back per mesh | yes |
| `modify_meshes` | Write | Base level, skirt and display of simple terrains, preserving topology | yes |
| `get_view_settings` | Read | Settings or native error for each of up to 100 views | yes |
| `set_view_settings` | Write | Scale and existing layer combination of views; preserve other settings | yes |
| `list_layer_combinations` | Read | Saved combinations, optional per-layer states, filter/page before details | yes |
| `set_layer_settings` | Write | Existing layer visibility, locking, wireframe and intersection group | yes |
| `create_sections` | Write | Straight sections with a new name, read back on the story and in the Project Map | yes |
| `create_favorites_from_elements` | Write | New favorites captured from existing elements, never overwriting; names read back | yes |
| `update_favorites_from_elements` | Write | Overwrites existing favorites from elements of their type | yes |
| `set_attribute_property_values` | Write | Custom property values on building materials, composites, profiles and other attributes, as text | yes |
| `create_interior_elevations` | Write | Interior elevations from a chain of points with a new name, read back on the story and in the Project Map | yes |
| `list_keynotes` | Read | Keynote folders and items with GUIDs and key paths (Archicad 28+) | yes |
| `create_keynote_folders` | Write | New keynote folders with new keys; only adds | yes |
| `create_keynote_items` | Write | New keynote items with title, description and reference; only adds | yes |
| `create_morphs` | Write | Box morphs from a base corner and size, read back by story, origin and 3D box | yes |
| `create_wall_thickness_dimensions` | Write | Associative thickness dimensions on existing walls, on the wall's story | yes |
| `create_associative_dimensions` | Write | Linear dimensions between wall ends, linked to the walls | yes |
| `create_openings` | Write | Rectangular Opening-tool openings in existing walls or slabs | yes |
| `read_scene_model` | Read | Rooms with suggested cameras and element boxes, to plan 3D scenes | no |
| `shoot_3d_scenes` | View | Sets 3D cameras and cuts and returns the 3D window images; puts the 3D window back | no (own add-on) |
| `save_3d_scenes` | Write | Saves 3D scenes as View Map views, one folder per room | no (own add-on) |
| `save_room_plan_views` | Write | Room enlargement views: a framed floor plan view per room, numbered, one folder per room | no (own add-on) |
| `create_composites` | Write | New composites from skins (building material by name, thickness, type, pen); only adds | yes |
| `create_drawings` | Write | Places views on existing layouts as Drawings | yes |
| `update_drawings` | Write | Updates every Drawing on layouts from its source view | yes |
| `add_stories` | Write | New stories above the top or below the bottom; existing stories kept | yes |
| `create_design_options` | Write | New design option sets, options and combinations (Archicad 29+); only adds | yes |
| `move_to_design_options` | Write | Puts elements in a design option or back in the main model (Archicad 29+) | yes |
| `create_solid_operations` | Write | Solid element operations between existing elements | yes |
| `trim_to_roof` | Write | Trims elements with a roof or shell | yes |
| `remove_solid_operations` | Write | Removes solid element operation links; the elements stay | yes |
| `modify_lamps` | Write | Edits lamps: position, level, size, light on or off | yes |
| `remove_trims` | Write | Removes a roof or shell trim from elements; the elements stay | yes |
| `create_classification_systems` | Write | New classification systems with their item trees | yes |
| `create_surfaces` | Write | New surfaces copied from an existing one, with a new colour, transparency or type | yes |
| `move_navigator_items` | Write | Moves View Map views and folders, or layouts and subsets, into other folders | yes |
| `list_grid_elements` | Read | Grid lines with start, end, story, layer and GDL parameters | no (own add-on) |
| `create_grid_elements` | Write | Draws grid lines from start and end points, with bubble text and other GDL parameters | no (own add-on) |
| `create_layout_subsets` | Write | New Layout Book subsets with prefix and numbering | yes |
| `place_hotlinks` | Write | Places hotlink modules from .mod or .pln files | yes |
| `get_attribute_details` | Read | Detailed composites, profiles, surfaces, material physics, zone categories, pen tables, lines or fills | yes |

### Reported live validation

The maintainer/Claude reported live checks on **Windows, Archicad 30 build 3001 BRA,
Tapir 1.7.0**, on 2026-10-11. Write tests used an **untitled, unsaved test project**;
the named CRM 005 project was used for earlier read-only diagnosis. These are recorded
operator results, not live tests executed by Codex during this documentation update.

| Scope | Recorded result |
|---|---|
| Discovery, Tapir/project/story/selection and element reads | Passed; multiple instances identified by port |
| Properties and BIM details | Read successfully; unavailable properties retain per-item status |
| Floor-plan polygons | Exact duplicates removed; missing cut fills remain an open upstream investigation |
| Bounding boxes, material reads and filtered searches | Live validation recorded as integrated in the task queue |
| Walls and slabs | Created and verified; wall-token reuse refused; slow upper-story slab motivated longer write timeout |
| Rectangular/circular columns | Verified after matching Archicad's circular linked-dimension normalization |
| Objects | Known library name verified; native unknown-name error isolated per item |
| Movement and property writes | Verified XY/Z moves and element-ID property changes |
| Deletion | Only two test objects deleted and absence verified; original object preserved |
| Beams and zones | Rectangular beam and manually bounded zone verified |
| Preview names and library parts | Story/layer names shown; library inventory was partial, with 92 unreadable parts |
| Manual smoke and `.mcpb` extension | Untitled-project smoke verified; Claude Desktop extension connected on Windows |

All tools also have simulated unit coverage. Source-derived fixtures are explicitly marked
as such; recorded captures identify their live environment. See [ESTADO](docs/ESTADO.md)
and [the task queue](docs/FILA.md) for the operator's evidence and remaining work. Partial
library preflight behavior is being corrected in PR #26; it is not a reason to treat an
incomplete inventory as proof that an object name is absent.

## Install

Requires [uv](https://docs.astral.sh/uv/) and, for most tools, the
[Tapir](https://github.com/ENZYME-APD/tapir-archicad-automation/releases) add-on in Archicad.

### Claude Desktop (one click)

Download `archicad-mcp-aberto-<version>.mcpb` from the
[releases](https://github.com/vitormartins-arq/archicad-mcp-aberto/releases) and open it
(or drag it onto Settings > Extensions in Claude Desktop). The extension asks for the ports
to scan and the write timeout; the defaults work for a normal install.

To build the bundle yourself from a clone: `npx @anthropic-ai/mcpb@2.1.2 pack .`

### Manual configuration (Claude Desktop, Codex and other clients)

From a clone:

```json
{
  "mcpServers": {
    "archicad": {
      "command": "uv",
      "args": ["run", "--directory", "C:/path/to/archicad-mcp-aberto", "archicad-mcp-aberto"]
    }
  }
}
```

Without a clone, straight from GitHub:

```json
{
  "mcpServers": {
    "archicad": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/vitormartins-arq/archicad-mcp-aberto", "archicad-mcp-aberto"]
    }
  }
}
```

In Codex, add the same command to `~/.codex/config.toml`:

```toml
[mcp_servers.archicad]
command = "uvx"
args = ["--from", "git+https://github.com/vitormartins-arq/archicad-mcp-aberto", "archicad-mcp-aberto"]
```

Then install Tapir for your Archicad version from its
[releases](https://github.com/ENZYME-APD/tapir-archicad-automation/releases).

Set `ARCHICAD_MCP_PORTS` (for example `19723-19730`) to change the scanned ports.
Ports must be between 1 and 65535, and ranges must be ascending. Invalid entries
stop startup with an `ARCHICAD_MCP_PORTS` error before discovery; range endpoints
are validated before expansion. Duplicate ports are scanned only once, in the
order configured.

## Safety rules

- With several instances open, nothing runs without an explicit target. The server
  never picks the first port.
- "Busy" (error 4001) is reported as busy, not as a missing add-on.
- Heavy reads (floor plan polygons) only run when asked for.
- `create_walls` dry-runs by default. Review the plan with the user before applying;
  writes have per-wall receipts and a geometry check after applying. No tool saves the project.

## Wall creation

`create_walls` accepts `walls`, an optional `port`, `dry_run` (default `true`), and
`confirmation_token`. It creates straight walls, Basic or of a composite. Lengths
are metres. Each wall needs `start`, `end`, `floor_index`, `height` and `thickness`
(or `composite`, below):

```json
{
  "walls": [{
    "start": {"x": 0, "y": 0},
    "end": {"x": 4, "y": 0},
    "floor_index": 0,
    "height": 3.0,
    "thickness": 0.2
  }],
  "port": 19723
}
```

Optional wall settings are `bottom_offset` (relative to the chosen story), `offset`,
`reference_line` (`Outside`, `Center` or `Inside`), `composite` and `favorite`. New
walls inherit Archicad's current default layer and building material. `composite` names
a Composite attribute for walls: the preview reads its skins with `GetComposites`, the
wall's thickness is their total (a different `thickness` is refused), and the read-back
checks the structure and the composite.

The default call only reads the target and returns a preview. After the user reviews
it, repeat the same wall inputs with the preview's explicit port, `dry_run: false`
and its `confirmation_token`. Tokens expire in ten minutes, belong to one client
session and are consumed once. Changed inputs, project information, story structure
or element IDs require a new preview. Invalid input rejects the batch before writing.

Apply returns one receipt item per input wall, including a unique `wall_receipt_id`,
parameters, the created GUID or the original Tapir error, and verification results.
A failed wall does not hide successful walls. Local JSON receipts are written before
and after dispatch to `~/.archicad-mcp-aberto/receipts`; set
`ARCHICAD_MCP_RECEIPTS_DIR` to use another folder. If the prepared receipt cannot be
written, creation is blocked. If the response is lost, the outcome is `unknown`;
inspect the model and do not retry the same batch. Writes and their verification wait up to 120 s
(set `ARCHICAD_MCP_WRITE_TIMEOUT` in seconds); reads keep the 12 s default. `unverified` and
`verification_failed` also require review. Partial successes are not rolled back
automatically. The server never saves the Archicad project.

This create-only implementation is tested against the fake Archicad. Its response
fixtures reuse earlier captured Tapir 1.7.0 responses; no new live tests were run for
this scope. Live validation and Undo are separate work.

## Safe slab creation

`create_slabs` shares the wall preview, single-use confirmation token, explicit port,
local receipts and post-write verification. Pass up to 20 `slabs`, each with `outline`
(3 to 200 `{x, y}` points in metres), `floor_index`, positive `thickness` and `level`.
`level` is absolute project Z: a slab at 3.15 m on a 3 m story has a 0.15 m offset.
Straight edges and simple concave polygons are supported; no holes or arcs.
The top reference plane is explicit. Layer, material and structure inherit defaults;
incompatible defaults or changed geometry are reported by verification.
Each slab has its own `slab_receipt_id`. The server never saves the project.

The fixture `tests/fixtures/tapir170_create_slabs_documented.json` records pinned
Tapir 1.7.0 source links. It is documentation/source-derived, **not a live capture**.
This delivery was tested only against the simulated Archicad.

## Element bounding boxes

`get_bounding_boxes` reads 1 to 500 `element_ids` (GUID strings), with optional
`port` and `mode: "2d"` (default) or `"3d"`. It uses the official JSON API without
Tapir and refuses an ambiguous destination when multiple instances are open.

The response contains `port`, `mode` and `boundingBoxes` in input order. Each item
has `guid` and either `box` or the original per-element `error`; one missing element
does not hide other boxes. Coordinates are metres: xMin/yMin/xMax/yMax, plus zMin/zMax
for 3D. 2D boxes refer to the floor-plan view and 3D boxes to the 3D view, relative
to the global origin. Some element types may not support bounding boxes.

```json
{"element_ids": ["11111111-1111-1111-1111-111111111111"], "port": 19723, "mode": "3d"}
```

The fixture follows [Graphisoft's official JSON API documentation](https://archicadapi.graphisoft.com/archicadPythonPackage/archicad.html)
and Python wrapper. It is synthetic, not a live capture; this delivery was tested
only against the fake Archicad.

## Safe column creation

`create_columns` previews up to 20 straight columns using the same confirmation,
receipt and timeout policy as walls/slabs. Each column takes `origin: {x, y}`,
`floor_index`, positive `height` and `base_level` (absolute project Z, all in metres).
Use `section: "rectangular"` with positive `width`/`depth` (the default section), or
`section: "circular"` with positive `diameter` and no width/depth. The core is centered
and unrotated; rectangular dimensions are explicitly unlinked, circular dimensions linked.

Layer/material and other Column tool defaults are inherited. Verification checks
position, story, height, base levels, dimensions, section, rotation/anchor and that
the column is not slanted or profile-based; incompatible defaults require review.
The Tapir command cannot explicitly reset every inherited Column setting. Keep the
Column tool defaults straight with a basic section before a live run. Each result
has a `column_receipt_id`. Column detail fixtures reuse an operator-provided live capture
from AC30 build 3001 BRA on Windows with Tapir 1.7.0 (2026-10-11).
Codex ran only simulated tests for this correction.

## Roadmap

0. Foundation: connection, discovery, read tools, simulated Archicad, CI.
1. Safe writes: wall/slab/column/object/beam/zone creation, movement, property writes and
   guarded deletion delivered. Rotation, GDL parameters and limited wall editing now
   have simulated coverage; operator live validation remains. **← here**
2. Command gateway (every official and Tapir command) and batch scripts; `.mcpb` bundle.
3. Documentation tools: dimensions, views, publishing, view capture; GDL and libraries.
4. First public release.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). You do not need Archicad to contribute: the
unit tests run against a simulated Archicad.

## License

[MIT](LICENSE). Created by [Vitor Martins](https://github.com/vitormartins-arq), an architect in Brazil,
and open to everyone's contributions.

- Exact floor-plan polygon duplicates within each element are removed (same vertex order, 1e-9 m tolerance); `notes` reports the removed count. Different polygons are preserved.

- `find_elements` filters by `element_type`, `floor_index`, `layer_index` and optional `property_guid`/`operator`/`value`. Operators: `equal`, case-sensitive `contains`, `greater`, `less`. It returns total matches, offset, a page of up to 500 element IDs and read errors. Missing properties are refused; unavailable values do not match. Type filtering precedes detail reads, and story/layer filtering precedes property reads, in batches of 100. The target is resolved once per search, without extra connection probes for each property batch.

- `delete_elements` previews up to 50 GUIDs and applies only in an untitled test project (`isUntitled=true` from Tapir). It lists type/story/layer, refuses missing, hotlinked or non-editable elements, requires explicit port and a single-use token, writes per-element receipts and verifies absence. Uses Tapir `DeleteElements` and `FilterElements(IsEditable)`; `API.DeleteElements` is not an official JSON API command. Never saves, unlocks or automatically retries. Owned subelements may also be removed by Archicad.

- Existing-element previews show `floorIndex`/`floorName` and `layerIndex`/`layerName`. Layer names are fetched once per preview using Tapir GetAttributesByType(Layer); missing names are null. Renaming a story or layer does not invalidate the confirmation token; indices and story levels still do.

- `create_beams` previews up to 20 straight rectangular beams: `start`/`end` `{x,y}`, `floor_index`, absolute project `level`, positive `width`/`height`, all metres. Centered section, no slant/rotation/curves, independent width/height. Uses the shared single-use token, explicit port, durable per-beam receipts and timeout. Checks type/story/endpoints/absolute and story-relative level/section. Layer/material defaults are inherited; custom profiles fail verification. GetDetailsOfElements reports the first segment, so use a basic single-segment default for live testing. Source-derived Tapir 1.7.0 fixture, not live captured.

- `create_zones` previews up to 20 manually bounded zones with simple `outline` points `{x,y}` in metres, nonblank `name`/`number` strings and `floor_index`. Polygon validation matches slabs: 3–200 vertices, no holes/arcs, no repeated vertices or intersections. Explicitly closed outlines are normalized. Uses shared token/port/receipts/timeout and checks type/story/name/number/manual contour (vertex rotation/reversal allowed). Category, stamp and base defaults are inherited. Source-confirmed Tapir CreateZones; synthetic fixture, not live captured.

- `list_library_parts` reads available part GUIDs/indices/names/types using Tapir `GetAvailableLibraryParts` (registered since 1.5.0). Optional case-insensitive `name_contains`, `offset`, `limit` up to 500; partial inventory metadata is preserved. `create_objects` refuses unknown names with a complete inventory and ambiguous names in dry run. With a partial inventory, only missing items are marked `unconfirmed` with a warning; native creation resolves them per item at apply. It rechecks before applying; the selected part GUID is bound into the token. See [the source investigation](docs/LIBRARY_PARTS.md) for each confirmed command and the distinction from GetLibraries.

- `rotate_elements` previews up to 50 `rotations` (`guid`, `center:{x,y}` in metres, `angle` in radians). No copies/saves/unlocking. Refuses nonexistent/hotlinked/non-editable elements. Shared confirmation, receipts and timeout. Verifies endpoints or origin/angle where available; box-only verification supports multiples of pi/2 within 1 mm, because rotating an AABB cannot predict arbitrary shapes at other angles.

- `get_gdl_parameters` reads up to 100 Object GUIDs, preserving GDL types, dimensions, flags, values and per-item errors. `set_gdl_parameters` previews up to 100 `{element_guid,name,value}` changes to existing scalar parameters, then verifies read-back. Rejects arrays/dictionaries, hidden/fixed/disabled/locked parameters, hotlinks and locked elements. Strings, booleans and finite numeric values must match the parameter type; LightSwitch booleans map to On/Off. Metres/radians; token, explicit port, receipts and timeout shared; never saves.

- `modify_walls` accepts up to 50 `walls` entries with `guid` and at least one of `height`, `thickness`, `bottomOffset`, `begCoordinate`, `endCoordinate` (metres, native camelCase). Preview shows existing details and requested fields. Refuses curved/trapezoidal/polygonal, hotlinked, locked or missing walls and zero-length results. Direct thickness edits require Basic walls; height unlinks the top-story setting as the native command does. Single-use confirmation, explicit port, per-wall receipts, errors and read-back verification; never saves.

- `modify_slabs`, `modify_columns`, `modify_beams`, `modify_windows`, `modify_doors` and `modify_objects` work like `modify_walls`: up to 50 entries, each a `guid` plus at least one field, native camelCase, metres. Slabs: `thickness` (Basic only) and `level` from the slab's story. Columns: `origin`, `bottomOffset`, `height` (unlinks the top story, as Tapir does), `width`, `depth`. Beams: `begCoordinate`, `endCoordinate`, `level` from its story, `width`, `height`; curved and zero-length beams are refused. Windows and doors: `width`, `height`, `sillHeight` and `centerOffset` along the owner wall from its start, refused past the wall end. Objects: `origin` `{x, y}`, `level` from its story and `dimensions` `{x, y, z}`; Tapir 1.7.0 changes only x and y, so z (the height) is then set and read back through the part's `ZZYZX` GDL parameter, and a part without it is refused. Round or linked sections take one size for both. Tapir places slabs and objects on the story that holds their absolute z, so a level that would move one to another story is refused. Single-use confirmation, explicit port, per-element receipts and read-back verification through Tapir 1.7.0 `ModifySlabs`/`ModifyColumns`/`ModifyBeams`/`ModifyWindows`/`ModifyDoors`/`ModifyObjects`; never saves. Tested live on Archicad 30 build 3001 BRA with Tapir 1.7.0 except `modify_beams`; the object height fix awaits a new live run (see [docs/VALIDAR.md](docs/VALIDAR.md)).
- `modify_lamps` works like `modify_objects` (same fields, the height through `ZZYZX`)
  plus `lightIsOn`, by Tapir 1.7.0 `ModifyLamps`. The light colour is not offered: the
  Tapir source says Archicad discards it on write. Not tested live yet.

- `create_roofs` previews up to 20 roofs, each with `outline` (simple polygon, metres), `floor_index`, `level` (absolute project Z, as in `create_slabs`) and `thickness`. With `pivot_line` (`start`, `end`) and `angle` (radians, between 0 and π/2) it makes one plane rising on the left of the line direction. Without them it makes a multi-plane roof on the polygon as pivot polygon, with optional `levels` (1 to 16 `{height, angle}`, heights non-decreasing) and `eaves_overhang`; omitted values keep the Roof tool default. Roofs are always created Basic (one building material, the Roof tool's), because a Composite default ignores the thickness. Applying checks type, story, class, structure, thickness, level, slope, pivot line or levels, and the polygon (the pivot polygon for multi-plane roofs, whose contour grows by the overhang). Tapir 1.7.0 `CreateRoofs`; never saves. Tested live on Archicad 30 build 3001 BRA with Tapir 1.7.0.

- `create_texts` previews up to 20 plain texts with `text` (newlines make lines), `position` (metres), `floor_index`, `angle` (radians), optional `height_mm` (Archicad sizes text in paper millimetres) and `justification`. Font and other style come from the Text tool default. Applying checks type, story, position, text, angle (on the circle) and any size or justification you gave. Tapir 1.7.0 `CreateTexts`; never saves. Tested live on Archicad 30 build 3001 BRA with Tapir 1.7.0.

- `modify_roofs` and `modify_texts` follow the same pattern. Roofs: `thickness` (Basic only), `level` from the roof's story, `eavesOverhang` and `levels` (`{height, angle}`, heights non-decreasing); Tapir 1.7.0 `ModifyRoofs` edits only multi-plane roofs, so single-plane roofs are refused in the preview. Texts: `text`, `position` (the text stays on its story), `angle` (radians), `heightMm` (paper millimetres) and `justification`, through `ModifyTexts`; text is compared with LF line endings and angles on the circle. Tested live on Archicad 30 build 3001 BRA with Tapir 1.7.0.

- `list_classifications` without `system` lists the project's classification systems (GUID, name, version). With `system` (GUID or name, case ignored) it returns that system's items as a flat tree: `guid`, `id` (the code you see in Archicad), `name`, `parent_guid` and `depth`; `query` filters by id or name. `set_classifications` previews up to 100 `{element_guid, system, item}` changes; `item` is a GUID, an id code or a name, and `null` removes the element's classification in that system. Names that match several systems or items are refused, so pass the GUID. The preview shows the current and the new item and flags changes that change nothing; locked, hotlinked and missing elements are refused. Official JSON API `SetClassificationsOfElements`, read back with `GetClassificationsOfElements`; same token, port, receipts and timeout; never saves. Tested live on Archicad 30 build 3001 BRA with Tapir 1.7.0.

- `create_labels` previews up to 20 text labels. With `element_guid` the label is attached to that element and sits on its story (`floor_index` is refused); `position` is then optional and moves the leader start. A free label needs `position` (metres) and `floor_index`. Optional `height_mm` (paper millimetres); font and the rest come from the Label tool default. Applying checks type, story, class, text, owner and the position and size you gave. Tapir 1.7.0 `CreateLabels`; never saves. Tested live on Archicad 30 build 3001 BRA with Tapir 1.7.0; whether a free label draws a leader to the origin is still to be checked visually.

- `create_lines`, `create_polylines`, `create_arcs`, `create_circles` and `create_fills` draw 2D elements on a story: up to 50 per call, each with `floor_index` and optional `layer` (the layer name, case ignored) and `pen` (pen-table index 1 to 255). Lines take `start` and `end`; polylines take `points` (2 to 500, straight segments; repeat the first point to close); arcs take `center`, `radius`, `start_angle` and `end_angle` (radians, counter-clockwise); circles take `center` and `radius`; fills take a simple `outline` polygon, optional `fill` (the fill name, such as a hatch pattern) and `contour_pen` (`pen` is the fill pen). Names that match nothing or several attributes are refused. Line type and the rest come from the tool defaults. Applying reads back type, story, layer, geometry and pens; polyline and fill coordinates are compared within 1 mm (Archicad 30 answers error 7203 to `Get2DBoundingBoxes` for them), and a circle that reads back as a full Arc counts as a circle. Tapir 1.7.0 `CreateLineElements`, `CreatePolylines`, `CreateArcs`, `CreateCircles` and `CreateHatches`; never saves. Tested live on Archicad 30 build 3001 BRA with Tapir 1.7.0; the polyline, fill and circle checks were fixed after that run.

- `list_layers` lists every layer with its GUID, index, name, `isHidden`, `isLocked`, `isWireframe` and `intersectionGroupNr`. `create_layers` previews up to 50 new layers: `name` and optional `hidden`, `locked`, `wireframe` and `intersection_group`. A name the project already has (case ignored) or a name repeated in the call is refused in the preview; nothing is ever overwritten. Applying reads each new layer back. `set_element_layers` previews moving up to 100 editable elements to existing layers: `{element_guid, layer}`, the layer by name (case ignored, ambiguous names refused). The preview shows the current and the new layer and flags moves that change nothing; locked, hotlinked and missing elements are refused. Applying reads back layer, type and story. Tapir 1.7.0 `GetLayers`, `CreateLayers` (with `overwriteExisting: false`) and `SetDetailsOfElements`; never saves. Tested live on Archicad 30 build 3001 BRA with Tapir 1.7.0.

- `select_elements` and `highlight_elements` change only what you see in Archicad, never the model, so they act at once without a preview or token (marked "View" above). `select_elements` takes up to 100 GUIDs and a `mode`: `replace` (the default; an empty list clears the selection), `add` or `remove`; it reads the selection back and lists elements that did not end up selected. `highlight_elements` paints up to 100 elements in one `color` (`[r, g, b]` or `[r, g, b, a]`, 0 to 255, red by default), with optional `wireframe_3d` for the rest in 3D; an empty list clears the highlight. `get_element_groups` returns the group that directly holds each element (`null` when ungrouped) and the members of those groups. `create_groups` previews up to 20 groups of 2 or more elements (100 in all); locked, hotlinked, missing and already grouped elements are refused, and applying reads each group's members back. Tapir 1.7.0 `ChangeSelectionOfElements`, `HighlightElements`, `GetGroupsOfElements`, `GetElementsOfGroups` and `CreateGroups`; never saves. Tested live on Archicad 30 build 3001 BRA with Tapir 1.7.0.

- `get_project_info_fields` lists the File > Info > Project Info fields that title blocks show through autotext (`projectInfoId`, the visible `projectInfoName` and `projectInfoValue`). `set_project_info_fields` previews up to 30 `{field, value}` changes; `field` is the id or the visible name (case ignored, ambiguous names refused) and an empty `value` clears it. `CLIENT_FULLNAME` is refused: Archicad keeps it empty when written, so set the given and family name fields. Applying writes one field at a time, stops at the first lost answer, and reads every field back. `list_favorites` returns the favorite names of one element type (`Wall`, `Slab`, `Window` and so on). `apply_favorites` previews applying a favorite by name to up to 50 editable elements; the name must be a favorite of that element's own type, and outer spaces and case are ignored when the exact name does not match (Archicad 30 BRA ships favorites such as " Parede Genérica - Default"). Archicad applies its settings, classifications, categories and properties, never geometry; Tapir cannot read a favorite's settings, so applied items stay `unverified` and the receipt shows the layer before and after. Tapir 1.7.0 `GetProjectInfoFields`, `SetProjectInfoField`, `GetFavoritesByType` and `ApplyFavoritesToElements`; never saves. Tested live on Archicad 30 build 3001 BRA with Tapir 1.7.0.

- `lock_elements` and `unlock_elements` use Archicad's manual lock (Edit > Locking), not Teamwork reservation. Each takes up to 100 element GUIDs. Lock refuses missing, hotlinked or already non-editable elements; unlock refuses elements that are already editable or sit on a locked layer (unlocking those would not make them editable). Tapir answers one result for the whole batch, so the MCP reads every element's editability back. `update_zones` runs Design > Update Zones on every zone of the project at once (there is no per-zone choice), with `keep_stamp_position` (default true), `undo_top_trim` and `undo_bottom_trim`; the preview counts zones and the result stays `unverified`, so check areas and stamps in Archicad. Tapir 1.7.0 `LockElements`, `UnlockElements`, `FilterElements` and `UpdateZones`; never saves. Tested live on Archicad 30 build 3001 BRA with Tapir 1.7.0, `update_zones` only with a manual zone.

- `list_property_groups` lists the groups of Options > Property Manager with their GUID, whether each is custom and how many properties it holds. `create_property_groups` previews up to 20 new, empty custom groups (`name`, optional `description`); a name already in use is refused. `create_properties` previews up to 50 custom properties, each in an existing custom group (by name or GUID): `type` is one of Tapir's `number`, `integer`, `string`, `boolean`, `length`, `area`, `volume`, `angle`, their `...List` forms, `singleEnum` or `multiEnum`; optional `description`, `editable` (default true) and `default` (meters and radians; an enum default names its options); `enum_values` for enums; and where it is available, as classification items by GUID, id or name (`available_for`) and/or every item of one classification system (`available_for_system`). A property available for no classification is created, with a warning, because Archicad only shows custom properties on elements whose classification they are available for. Built-in groups and names already in the group are refused; nothing existing is changed or deleted. Each new group and property is read back with `GetAllProperties` (type, group, editability, description, options, availability and enum default). Tapir 1.7.0 `GetAllProperties`, `CreatePropertyGroups` and `CreatePropertyDefinitions`; never saves. Tested live on Archicad 30 build 3001 BRA with Tapir 1.7.0.

- `create_worksheets` and `create_details` preview up to 20 empty independent Worksheet or Detail viewpoints, each with `name` and `reference_id`; one that already has the same name and ID is refused. `create_layouts` previews up to 20 layouts, each with `name` and `master` (the name of an existing master layout, case ignored, ambiguous names refused). Tapir's `CreateLayout` would quietly create a master layout that does not exist, so the MCP always sends the master's Navigator ID and refuses a missing master; size and margins come from the master. A layout name already in the Layout Book is refused. Each new database is found back in the Navigator (`GetNavigatorItemTree` and `GetDatabaseIdFromNavigatorItemId`) and its name (and ID, for worksheets and details) compared. Tapir 1.7.0 `CreateWorksheets`, `CreateDetails` and `CreateLayout`; never saves. Tested live on Archicad 30 build 3001 BRA with Tapir 1.7.0.

- `rename_items` renames template items of one `kind` in bulk: `view_map`, `project_map` or `layout_book` items (the map's root is left alone), `favorites`, `classification_systems`, `classification_items` (both the id, which BRA uses for the item text, and the name), custom `property_groups` and `properties` (built-in ones are left alone), `building_materials`, `layers`, `layer_combinations` (each layer's hidden, locked, wireframe and intersection group state is compared before and after, so a rename that changed them reads as `verification_failed`) or `attribute_folders` (the folders of the layer, layer combination, building material, surface... dialogs; `scope` names the attribute type, such as `Layer`; the root folder is left alone, and names must be unique within their parent folder and must not start or end with a space). Pass either `find` and `replace` (every name that contains `find`; an empty `replace` removes it) or `renames`, a list of exact `{old, new}` names; `scope` narrows classification items to one system, properties to one group and favorites to one element type. Each item keeps its GUID, so elements, views and schedules that use it follow the new name; a renamed Navigator item gets a custom name, as when renamed by hand. Names that would clash (attributes, favorites, systems and groups across the project, item ids within a system, properties within a group) and blank names are refused; up to 500 renames per call. Every name is read back. Tapir 1.7.0 `RenameNavigatorItem`, `RenameFavorites`, `UpdateClassificationSystems`, `UpdateClassificationItems`, `UpdatePropertyGroups`, `UpdatePropertyDefinitions`, `CreateBuildingMaterials`/`CreateLayers`/`CreateLayerCombinations` with `overwriteExisting` and the attribute's GUID (only the name is sent, plus the empty `layers` list that `CreateLayerCombinations` requires; Tapir seeds an overwritten combination from its own layer table), and the official `API.GetAttributeFolderStructure` and `API.RenameAttributeFolders` for folders. Model View Options, Graphic Overrides and their rules have no Tapir 1.7.0 command, so they cannot be renamed yet. `surfaces` is refused: in the live test `CreateSurfaces` with only the name also changed each surface's texture. A call Archicad refuses outright (`succeeded: false`) is reported as `failed`, not `unknown`. Never saves. Tested live on 14/10/2026 (Archicad 30 build 3001 BRA, Tapir 1.7.0) except `layer_combinations`, which failed there before the `layers` fix.

- `run_read_command` runs one command from the closed read-only lists in [docs/GATEWAY.md](docs/GATEWAY.md): `API.<Command>` for the official JSON API or `Tapir.<Command>` for Tapir, with its JSON `parameters` sent unchanged and the response returned raw. Unlisted names, writes and saves are refused before anything reaches Archicad. Prefer a dedicated tool when one exists.

- `create_windows` and `create_doors` preview up to 20 openings, each with `wall_guid`, `center_offset` (metres along the wall's reference line from its start) and optional `sill_height`, `width`, `height` and `favorite_name`. Tapir 1.7.0 `CreateWindows`/`CreateDoors` take no library part name: the Window or Door tool default decides the part, or an existing favorite (checked in the preview with `GetFavoritesByType`). The preview refuses missing, non-wall, curved or polygonal, hotlinked and locked owners and offsets past the wall end. Applying checks type, story, owner wall, offset and any size or sill you gave, and reports the library part Archicad placed (with a favorite, that is the part name, not the favorite name). The exact favorite name wins; otherwise outer spaces and case are ignored, and the exact name is sent. Same token, port, receipts and timeout; never saves. Tested live on Archicad 30 build 3001 BRA with Tapir 1.7.0.


- `modify_labels` edits existing Text labels with `{guid, text?, height_mm?}`. Text is
  normalized to LF; `height_mm` is the character size in paper millimetres. Preview and
  apply use the shared single-use confirmation, explicit port, receipts, editability
  checks and read-back. Symbol labels and unsupported fields are refused. Tapir 1.7.0
  `ModifyLabels` does **not** accept coordinates or a story, so this tool preserves the
  owner and position; use a separate `move_elements` preview for movement. Text/size edits
  can rebuild rich text as one paragraph and disable word wrap in the native command.
  Source-derived simulation only; live validation pending.


- `list_issues(port?, query?, offset=0, limit=200)` lists issue GUIDs, names, tag text and
  native metadata through Tapir 1.7.0 `GetIssues`; filtering is case-insensitive on name
  and tag, before pagination. `create_issues([{name, tagText?}], ...)` creates up to 20
  incidences, and `attach_elements_to_issue(issue_guid, element_guids, ...)` associates
  1–100 existing elements with one existing issue. Associations always use **Highlight**,
  never Creation, Deletion or Modification; existing links are retained. No BCF/export,
  saving or deletion. Writes preview by default; apply requires the identical inputs,
  explicit port and single-use token. Names/tags and each association are read back.
  Each native create/association is its **own Undo step**. A lost or malformed response
  stops the remaining writes without retrying, preserves prior results and marks later
  items `failed` with `not_attempted: true`. Source-derived simulation only; live validation pending.


- `get_navigator_tree(navigator_map="ProjectMap", port?, query?, offset=0, limit=200,
  publisher_set_name?)` reads a flattened Navigator tree through Tapir 1.7.0. Maps are
  `ProjectMap` (project), `PublicViewMap` (views), `LayoutBook` (layouts) and
  `PublisherSets` (one publisher set). Rows include `guid`, `name`, native `type`,
  `parent_guid`, `depth`, `prefix` and displayed `uiId`; the root is depth 0. Search
  matches name/type/uiId case-insensitively before pagination (limit up to 500); parent
  GUIDs and depth always refer to the original unfiltered tree. Pass an exact
  `publisher_set_name` with PublisherSets to read that set; omitting it returns **only
  the first set**, with a note. No publishing, writing or saving. Source-derived
  simulated coverage; live validation pending.


- `create_meshes([{outline, floor_index, level, skirt_type?, skirt_depth?, ridges?,
  show_lines?}], ...)` creates up to 20 simple terrains with 3–200 boundary vertices.
  Every `outline` vertex is `{x, y, z}` in **absolute project metres**, and `level` is
  the absolute base plane. The tool converts to story-relative mesh base and base-plane-
  relative vertex heights required by Tapir 1.7.0. A repeated closing point is normalized
  only when its Z also matches. The plan contour must be simple and nonzero, as for slabs.
  The default `skirt_type` is `SurfaceOnlyWithoutSkirt`; `WithSkirt` and
  `SolidBodyWithSkirt` use positive `skirt_depth` below the base plane (default 1 m), with
  the bottom strictly below every boundary vertex. `ridges` is `AllSharp` (default),
  `AllSmooth` or `UserDefined`; `show_lines` defaults to true. No holes, arcs or internal
  contours yet. Material/layer inherit Mesh tool defaults. `modify_meshes` takes
  `{guid, level?, skirt_type?, skirt_depth?, ridges?, show_lines?}` for up to 20 simple
  existing meshes, preserving the owner story and polygon; level translates the whole
  terrain vertically, without replacing vertices. Complex meshes are refused in the
  preview. Both tools use single-use tokens, explicit apply ports, receipts, per-item
  errors and read-back through `GetDetailsOfElements`; neither saves. Verified only
  against the source-derived simulator; live testing remains pending.


- `get_view_settings(view_guids, port?)` reads settings or an error per Navigator view,
  up to 100 GUIDs, preserving request order. `drawingScale` is the scale denominator
  (100 = 1:100); zoom uses model metres and rotation uses radians.
  `set_view_settings([{guid, drawing_scale?, layer_combination?}], ...)` previews/applies
  scale and/or an existing layer combination (exact name or GUID) for up to 100 views
  in PublicViewMap. It sends only requested fields and reads all other exposed settings
  back unchanged, including pens, graphic overrides, zoom and rotation. Existing layer
  combination definitions are also checked unchanged. Missing combinations/views,
  duplicate combination names and unsupported fields are refused. Setting a scale
  enables native stored-scale saving; Tapir does not expose that flag for verification.
  Navigator settings have **no guaranteed Undo** through this command; previews and
  durable receipts retain previous values for restoration manually or by a new
  preview/apply. Other write tools keep their existing Undo note. Never saves or publishes.
  Source-confirmed Tapir 1.7.0 GetViewSettings/SetViewSettings; simulated only.

### Registry snapshot — 2026-10-14 development stack

The expanded registry in this stack contains **77 tools: 24 read-only and 53 write or
interaction tools**. The smaller Phase 1 count near the beginning is historical. New
Codex tools (labels, issues, Navigator, meshes and view settings) have simulated coverage;
this does not imply live or visual approval. See docs/VALIDAR.md for the operator checklist.

- Geometry read-back uses fixed absolute numeric tolerance (1e-7), and moved bounding
  boxes keep a fixed 1 mm tolerance. These do not grow with georeferenced coordinates:
  moving the model far from the origin must not turn millimetre errors into `verified`.


- `list_layer_combinations(port?, query?, offset=0, limit=200, include_layers=false)`
  lists saved combination GUIDs/names/indices. With `include_layers`, each result adds
  native per-layer hidden/locked/wireframe/intersection-group states or a per-item error;
  details are fetched only after filtering/pagination, in batches of 100.
  `set_layer_settings([{layer, hidden?, locked?, wireframe?, intersection_group?}], ...)`
  targets up to 50 existing layers by exact name or GUID. It sends unchanged name/GUID
  plus only requested fields through Tapir 1.7.0 CreateLayers with overwriteExisting,
  and verifies identity, name, flags and group. The protected first Archicad layer,
  duplicate aliases and unknown layers are refused. It affects current layer attributes;
  it is not an editor for the saved combination tables. No guaranteed attribute Undo:
  keep the receipt's before values to restore manually or with a new preview/apply.
  The native generic base can create a layer if a target disappears between preflight
  and dispatch; a different returned GUID is marked `unknown`, never verified or
  automatically removed/retried. No deletion, renaming or saving. Source-derived tests
  only; live validation pending. Registry after this addition: **79 tools (25 reads,
  54 writes/interactions)**.

- T23 custom Project Info field creation is blocked by native Tapir 1.7.0 limitations:
  AC30 explicitly rejects creation, and the reader filters generated custom field IDs.
  See [source investigation](docs/T23-PROJECT-INFO-FIELDS.md). No creation tool is exposed
  until complete preflight and independent read-back are possible.

- `add_comment_to_issue(comments, port?, dry_run=true, confirmation_token?)` adds 1–20
  comments: each item has `issue_guid`, `text`, optional `author` (default API).
  Preview binds existing issue metadata and comments; apply needs explicit port and a
  single-use token. New comment GUID/text/author/status and unchanged old comments are
  checked via GetCommentsFromIssue. Each comment is a separate Undo step; no attachments,
  deletion or saving. Tapir 1.7.0 source-derived simulated coverage; live test pending.

- `create_view_map_folders(folders, ...)` adds 1–20 `{name, parent_guid}` folders.
  `clone_to_view_map(views, ...)` adds 1–20 `{source_guid, parent_guid}` clones from
  ProjectMap. Parents must be existing project folders or subfolders in PublicViewMap; the synthetic
  map root (depth 0) is refused. Get GUIDs with
  `get_navigator_tree`. Both require preview, one-use token and explicit apply port,
  retain receipts and independently verify GUID/name/type/parent and prior tree rows.
  Native clone settings are inherited. No guaranteed Navigator Undo: remove unwanted
  new items manually. Never moves/deletes/saves/publishes. Source-derived tests only.

- `create_classification_items(items, ...)` adds 1–50 `{system_guid, parent_guid,
  id, name, description?}` items under existing classification parents. IDs must be
  new across the entire selected system (case-insensitive); no recursive children or
  new systems. Preview binds the tree; explicit apply port, one-use token and receipts.
  The pinned Tapir command omits success rows (`executionResults: []`); one native call
  per item and independent official tree read-back verify the new GUID/ID/name/description/parent
  and unchanged prior items. Each item is a separate Undo step. Never deletes/saves.
  Tapir 1.7.0 source-derived simulation only; live/operator validation pending.

- View Map clone verification also checks the native `sourceNavigatorItemId` GUID;
  identical names/types/IDs cannot stand in for source identity. Navigator reads expose
  `source_guid` when present plus native inheritance flags (`custom_name`, `custom_ui_id`,
  `is_independent`), which are bound to previews and checked unchanged for prior items.
  Only leaf Project Map viewpoints may be cloned. Folder names must fit 255 UTF-16 units
  without NUL; this accounts for the native Unicode name buffer, including emoji.

- `create_sections([{start, end, floor_index, name, depth?}], port?, dry_run?,
  confirmation_token?)` creates up to 20 straight sections through Tapir 1.7.0
  CreateSections. Coordinates are metres; the section looks to the left of start->end,
  as far as `depth` (default 1 m, Tapir's default). The marker and the rest come from
  the Section tool default, and Archicad numbers the reference ID. The name must be new
  in the Project Map: each section is read back as a CutPlane on its story and as the
  one SectionItem of that name, whose reference ID goes into the receipt. Fixtures come
  from the Tapir source, not a live capture. Registry: **80 tools (25 reads, 55
  writes/interactions)**.

- `create_favorites_from_elements([{element_guid, favorite, folder?}], port?, dry_run?,
  confirmation_token?)` saves up to 50 new favorites through Tapir 1.7.0
  CreateFavoritesFromElements. Each one copies an existing element's settings,
  classifications and editable property values; `folder` is an optional list of folder
  names in the Favorites palette. The name must be new for that element type, so an
  existing favorite is never overwritten; locked elements are fine, since they are only
  read. Each new name is read back with GetFavoritesByType. Fixtures come from the Tapir
  source, not a live capture. Registry: **81 tools (25 reads, 56 writes/interactions)**.
- `update_favorites_from_elements([{element_guid, favorite}], port?, dry_run?,
  confirmation_token?)` overwrites up to 50 existing favorites through Tapir 1.7.0
  `UpdateFavoritesFromElements`, each from one element of the favorite's type. The old
  settings are not kept, so the preview says to copy them first with
  `create_favorites_from_elements` when they matter. Tapir cannot read a favorite's
  settings, so a successful receipt stays `unverified`.

- `set_attribute_property_values([{attribute_guid, property_guid, value}], port?,
  dry_run?, confirmation_token?)` writes up to 100 custom property values on attributes
  through Tapir 1.7.0 SetPropertyValuesOfAttributes. Tapir handles these values as
  display text and Archicad converts the text with the project's own formats, so `value`
  is text, written in the format the preview shows for the current value (for example
  "120,00" in a Brazilian project). Read-only, unknown and unavailable properties are
  refused in the preview; each value is read back as text, and a value Archicad stores
  in another format shows as `verification_failed` with the text it kept. Attribute
  GUIDs come from `list_building_materials` or the other attribute reads. Fixtures come
  from the Tapir source, not a live capture. Registry: **82 tools (25 reads, 57
  writes/interactions)**.

- `create_interior_elevations([{nodes, closed?, floor_index, name, reference_id?,
  depth?}], port?, dry_run?, confirmation_token?)` creates up to 20 interior elevations
  through Tapir 1.7.0 CreateInteriorElevations. `nodes` are 2 to 50 points in metres;
  each consecutive pair is one segment that looks to its left, as far as `depth`
  (default 1 m). Walking a room's corners anticlockwise with `closed: true` looks at all
  of its walls from inside. Marker and settings come from the Interior Elevation tool.
  The name must be new in the Project Map; each one is read back as an
  InteriorElevation on its story and as the Project Map item(s) of that name, whose
  reference IDs go into the receipt. Fixtures come from the Tapir source, not a live
  capture. Registry: **83 tools (25 reads, 58 writes/interactions)**.

- `list_keynotes(port?)`, `create_keynote_folders([{key, title, parent_folder_guid?}])`
  and `create_keynote_items([{key, title?, description?, reference?,
  parent_folder_guid?}])` (each write with `port?, dry_run?, confirmation_token?`) work
  with keynotes through Tapir 1.7.0 on Archicad 28 or newer. The writes only add: a key
  that already exists anywhere in the keynote tree is refused, so existing keynotes never
  change. New entries go in the root or in an existing folder from `list_keynotes`; to
  fill a new folder, create it first and use the GUID in its receipt. Each new entry is
  read back by GUID. Fixtures come from the Tapir source, not a live capture.

- `create_morphs([{base_point: {x, y, z}, size_x, size_y, size_z, floor_index}], port?,
  dry_run?, confirmation_token?)` creates up to 50 box morphs through Tapir 1.7.0
  `CreateMorphs`. The base point is the box's lowest corner in absolute project metres;
  sizes are positive metres along the project axes. Building material, surface and
  display settings come from the Morph tool defaults. The box is sent as an explicit
  closed solid body, because Tapir's own `size` box came out open (five faces, Surface)
  in a live test. Each morph is read back for type, story, origin, axes and a closed
  six-face Solid body, and its 3D bounding box must match within 1 mm. A morph on a
  story that Archicad is not showing makes Archicad open a dialog that blocks the API
  until someone clicks it, so show that story first. Fixtures come from the Tapir
  source, not a live capture.

- `create_wall_thickness_dimensions([{wall_guid, reference_point?: {x, y}, direction?:
  {x, y}}], port?, dry_run?, confirmation_token?)` adds up to 50 associative dimensions of
  both faces of existing editable walls through Tapir 1.7.0
  `CreateWallThicknessDimensions`, one per wall. The dimension goes on the wall's story
  and stays linked to the wall. By default its line crosses the middle of the wall's
  reference line, perpendicular to it; a curved wall needs an explicit direction. Display
  settings come from the Dimension tool defaults. Tapir returns no dimension-specific
  details, so the read-back checks the new element's type and story. Fixtures come from
  the Tapir source, not a live capture.

- `create_openings([{owner_guid, base_point: {x, y, z}, width, height}], port?, dry_run?,
  confirmation_token?)` cuts up to 50 rectangular openings of the Opening tool (Archicad
  26 or newer) into existing editable walls or slabs through Tapir 1.7.0
  `CreateOpenings`. The base point is in absolute project metres and its z is the
  opening's bottom edge; width and height are positive metres. Tested live, the width is
  centred on the base point and follows the wall's direction; in a slab the opening lies
  flat, its height running towards -y from the point. Tapir sets the opening's frame
  itself, and the shape, extrusion and display come from the Opening tool defaults.
  Tapir returns no opening-specific details, so the read-back checks the new element's
  type and that the host lists it among its connected openings (`GetConnectedElements`).
  Fixtures come from the Tapir source, not a live capture.
- 3D scenes ("generate the 3D scenes"): `read_scene_model(port?, min_z?, max_z?)` reads
  zone name, number, area and 3D box with the official API, plus element boxes, and
  suggests a level one-point camera per room (and a two-point one in big rooms).
  `shoot_3d_scenes(scenes, port?, image_format?)` sets up to 8 scenes and returns their
  images; a scene is `{name, folder?, camera, target, view_cone?, two_point?}` or
  `{name, folder?, parallel: {azimuth?}, cut_height?}` (a horizontal 3D cut, absolute
  metres). `save_3d_scenes(scenes, folder_path, port?, dry_run?, confirmation_token?)`
  saves up to 60 as View Map views in `folder_path + [folder]`, creating missing folders;
  the first folder name is found at any depth. Both put the 3D camera and cut back. They
  need this project's own add-on (`addon/`); the photographer rules are in
  `docs/3D_SCENES.md`.
- `save_room_plan_views(folder_path, rooms?, stories?, prefix?, first_number?, margin?,
  scale?, layer_combination?, port?, dry_run?, confirmation_token?)` saves room
  enlargement views: for each zone (all, or `rooms` by name, label or number, on
  `stories`), its story's floor plan as a View Map view framed on the zone's box plus
  `margin` metres (0.5 by default), at `scale` (25 for 1:25 by default, `null` keeps the
  story's) and an optional existing `layer_combination`. Views go into `folder_path +
  [room]` and are numbered by story and zone number: "AMP 01 - BANHO", "AMP 02 -
  COZINHA". Preview first; each saved view's zoom, scale and layers are read back. It
  needs the add-on's `SaveStoryView`; View Map changes are outside Undo.
- `create_walls`, `create_slabs`, `create_columns` and `create_beams` take an optional
  `favorite`: the name of a favorite of that tool in the open project (case and outer
  spaces ignored; the preview refuses a name that is missing or of another type). Tapir
  1.7.0 applies the favorite to the tool defaults first and the given fields override
  it, so with a favorite the settings it holds may be left out: slab thickness,
  column height and section, beam width and height. Walls are the exception: Tapir
  1.7.0 `CreateWalls` requires height and thickness even with a favorite (refused live
  on 21/10/2026) and sets the structure to Basic, the reference line, the bottom and
  an unlinked top over it, so a wall keeps only the favorite's layer, pens, materials
  and the like. Pass the favorite's `composite` to keep a composite wall. The
  read-back checks the geometry and the fields that were given. `create_zones`,
  `create_texts`, `create_labels`, `create_meshes` and the 2D drafting tools (lines,
  polylines, splines, arcs, circles, fills and hotspots) take `favorite` the same way;
  a mesh's skirt, ridges and line display come from the favorite unless given.
  `create_objects` does not yet (the library part comes from the name). Fixtures come
  from the Tapir source, not a live capture.
- `create_splines([{points, closed?, floor_index, layer?, pen?}], port?, dry_run?,
  confirmation_token?)` draws up to 50 2D splines by Tapir 1.7.0 `CreateSplines`. Each
  goes through 3 to 500 points in metres; Archicad smooths the curve itself (the Bezier
  handles are not settable). `closed` joins the last point back to the first, so the
  first point is never repeated. Layer and pen work as in `create_polylines`. The
  read-back compares type, story, layer, pen, `closed` and the stored points within
  1 mm. Fixtures come from the Tapir source, not a live capture.
- `create_hotspots([{position, height?, floor_index, layer?, pen?}], port?, dry_run?,
  confirmation_token?)` places up to 50 2D hotspots by Tapir 1.7.0 `CreateHotspots`:
  position in metres, optional height (the hotspot's z on its story, metres), layer by
  name and pen index. The read-back compares type, story, layer, position, height and
  pen. Fixtures come from the Tapir source, not a live capture.
- `create_keynote_labels([{keynote_item_guid, position, content_fields?}], port?,
  dry_run?, confirmation_token?)` places up to 20 keynote labels by Tapir 1.7.0
  `CreateKeynoteLabels` (Archicad 28 or newer). The item GUID comes from
  `list_keynotes`, and the preview refuses one that is not in the tree. The label text
  is the item's autotext for `content_fields` (Key, Title, Description, Reference; all
  by default). Tapir puts the label on the story Archicad shows and attaches it to
  nothing; the receipt reports the story and the text read back. The read-back checks
  type, class and position. The keynotes are never changed. Fixtures come from the
  Tapir source, not a live capture.
- `modify_morphs([{guid, size?, buildingMaterial?, surface?, castShadow?,
  receiveShadow?}], port?, dry_run?, confirmation_token?)` edits up to 50 morphs by
  Tapir 1.7.0 `ModifyMorphs`. Tapir rebuilds the whole body on a size change, so only a
  box as `create_morphs` makes (corner at the origin) is resized, and the corner stays;
  any other morph is refused in the preview. Building material and surface are given by
  name. The read-back checks each changed field and the new box size within 1 mm.
  Moving and rotating stay with `move_elements` and `rotate_elements`: Tapir's
  `rotationDegreesZ` mixes the x and z rows of the transform in the 1.7.0 source, which
  looks like a turn about Y, so it is not exposed until checked live.
- `create_associative_dimensions([{points: [{wall_guid, end}], reference_point,
  direction?}], port?, dry_run?, confirmation_token?)` adds up to 50 linear dimensions
  between end points (`start` or `end`) of existing straight walls by Tapir 1.7.0
  `CreateAssociativeDimensions`, 2 to 20 points each, all on one story. The dimension
  stays linked to the walls. Its line passes through `reference_point`; `direction`
  defaults to the first wall's direction. Tapir's own example gives `inIndex` 1 and 2 as
  the two ends of the reference line. The read-back checks type and story, then reads
  `GetDimensionData` and compares each witness point's wall and position within 1 mm. A
  section or elevation window in front makes Tapir fail, so show a floor plan.
- `create_lamps` works like `create_objects` for Lamp library parts, by Tapir 1.7.0
  `CreateLamps`: the preview checks the name among the loaded Lamp parts (an Object
  part is refused, as Tapir's `CreateObjects` refuses lamps), and `favorite` takes a
  Lamp favorite. Size and light stay the part's defaults.
- `create_zone_categories([{name, code?, color?: {red, green, blue}}], port?, dry_run?,
  confirmation_token?)` adds up to 50 zone categories by Tapir 1.7.0
  `CreateZoneCategories`. It never overwrites: a name the project already has, or a
  repeated name, is refused in the preview. Colours go from 0 to 1. Tapir copies the
  zone stamp from the project's first category. The read-back is `GetZoneCategories`
  (name, code and colour).
- `create_composites([{name, use_with, skins: [{building_material, thickness, type?,
  pen?}], separator_line?, separator_pen?}], port?, dry_run?, confirmation_token?)` adds
  up to 20 composites by Tapir 1.7.0 `CreateComposites`. `use_with` lists Wall, Slab,
  Roof or Shell; each of up to 20 skins takes a building material by name, a thickness
  in metres, a type (Core by default, Finish or Other) and a frame pen (1 by default).
  Every separator line gets `separator_line` (default: the project's first line type,
  the solid line) and `separator_pen`. A name the project already has, a repeated name,
  or a building material or line type that does not exist is refused in the preview,
  because Tapir would silently keep the default material for a GUID it cannot find.
  The read-back is `GetComposites`: use, skins (type, pen, thickness, material GUID) and
  separators (pen, line type GUID). Fixtures come from the Tapir source, not a live
  capture.
- `create_drawings([{view, layout, position: {x, y}, name?, angle?}], port?, dry_run?,
  confirmation_token?)` places up to 20 views on layouts by Tapir 1.7.0
  `CreateDrawings`. `view` is a View Map view name or any Navigator item GUID from
  `get_navigator_tree`; `layout` is a Layout Book layout name or GUID. The preview
  refuses folders, layouts, master layouts and placed Drawings, which Tapir cannot use as
  a source. `position` is the Drawing's centre on the layout in metres of paper; `name`
  sets a custom title; scale, title and frame come from the Drawing tool defaults, with
  the view's full extent. Tapir switches the window to the layout. The read-back finds
  the new Drawing on its layout (`GetElementsByType` with the layout database).
- `update_drawings(layouts, port?, dry_run?, confirmation_token?)` updates every Drawing
  on up to 20 layouts (name or GUID) by Tapir 1.7.0 `UpdateDrawings` (Archicad 27+). The
  preview lists the Drawings found on each layout. Tapir answers only success or
  failure, and Archicad has no read-back of a Drawing's update state, so a successful
  receipt stays `unverified`.
- `add_stories([{name, level, show_on_sections?}], port?, dry_run?,
  confirmation_token?)` adds up to 20 stories by Tapir 1.7.0 `SetStories`, which takes
  the whole story structure and would delete stories (and their elements) missing from
  it. The MCP sends every existing story back exactly as `GetStories` reads it, so the
  structure only grows. Each new story goes above the top story or below the bottom one
  (basements get negative indices); a level between two stories is refused, because it
  would renumber the stories the elements sit on. Names must be new and stories at
  least 1 cm apart. `structure_after` in the preview shows every story with its height
  after the change (the old top story's height becomes the gap to the first new one).
  The read-back checks the new stories and that the existing ones kept name and level.
- `create_design_options(sets?, options?: [{name, id, set}], combinations?: [{name,
  options}], port?, dry_run?, confirmation_token?)` adds design option sets, options and
  combinations by Tapir 1.7.0 (`CreateDesignOptionSets`, `CreateDesignOptions`,
  `CreateDesignOptionCombinations`; Archicad 29+), up to 20 of each, in that order, so an
  option can go in a set made in the same call and a combination can use new options.
  A combination names its active options by their string id. Existing set names,
  option ids and combination names are refused in the preview. Tapir does not report
  whether a combination's active options were set, so the read-back compares them, as
  well as each option's name, id and set. Elements are not moved into options.
- `move_to_design_options([{element_guid, option}], port?, dry_run?,
  confirmation_token?)` puts up to 100 elements in a design option by Tapir 1.7.0
  `MoveElementsToDesignOptions` (Archicad 29+). `option` is the option's string id from
  `list_design_options`; `null` takes the element back to the main model. The preview
  shows each element's current option and refuses missing elements and unknown ids. The
  read-back is `GetDesignOptionForElements`.
- `create_solid_operations([{target_guid, operator_guid, operation?,
  inherit_operator_attributes?, skip_polygon_holes?}], port?, dry_run?,
  confirmation_token?)` adds up to 50 links by Tapir 1.7.0 `CreateSolidElementLinks`,
  as Design > Solid Element Operations: `Subtraction` (default), `SubtractionUpwards`,
  `SubtractionDownwards`, `Intersection` or `Addition`. Both elements must exist, be
  editable and not hotlinked; a link that already exists between the two is refused.
  The read-back is `GetSolidElementLinks` (operation and flags).
- `trim_to_roof(element_guids, roof_guid, keep?, port?, dry_run?, confirmation_token?)`
  trims up to 100 editable elements with one roof or shell by Tapir 1.7.0
  `TrimElements`, as Design > Trim to Roof/Shell; `keep` is `KeepInside` (default),
  `KeepOutside` or `KeepAll`. The preview refuses a trimmer that is not a roof or shell
  and elements it already trims. The read-back is `GetElementTrims`.
- `remove_solid_operations([{target_guid, operator_guid}], port?, dry_run?,
  confirmation_token?)` and `remove_trims(element_guids, roof_guid, port?, dry_run?,
  confirmation_token?)` undo the two tools above by Tapir 1.7.0
  `RemoveSolidElementLinks` and `RemoveElementTrims`. The link or trim must exist; the
  elements stay. The preview shows what is removed, and the read-back checks it is gone.
- `create_classification_systems([{name, version, description?, source?, date?, items}],
  port?, dry_run?, confirmation_token?)` adds up to 10 systems by Tapir 1.7.0
  `CreateClassificationSystems`, each with a tree of up to 500 items (`id`, `name`,
  `description`, `children`). At least one item is required, because Tapir 1.7.0 gives
  no result for a system without items. A name and version already used is refused.
  Tapir does not report an error in a child item, so the read-back compares the whole
  tree, and the system's description, source and date.
- `create_surfaces([{name, based_on, color?, transparency?, material_type?,
  keep_texture?}], port?, dry_run?, confirmation_token?)` adds up to 50 surfaces by Tapir
  1.7.0 `CreateSurfaces`, never overwriting. Tapir starts a new surface from a zeroed
  record (black, no reflection), so each one copies every field of `based_on`, an
  existing surface, read with `GetSurfaces`, and changes only what is asked. The
  read-back compares every sent field.
- `move_navigator_items(map, [{item, folder}], port?, dry_run?, confirmation_token?)`
  moves up to 50 items by Tapir 1.7.0 `MoveNavigatorItem`: with `map` `view_map`, views
  and folders into a View Map folder; with `layout_book`, layouts and subsets into a
  subset or the top of the book. Names or GUIDs; a repeated name needs the GUID. An item
  already in the folder, or a folder into itself, is refused. One move per native call,
  each read back in the tree. The item goes to the start of the folder.
- `list_grid_elements(port?, include_parameters?)` and `create_grid_elements([{start,
  end, floor_index, layer?, parameters?: [{name, value}]}], port?, dry_run?,
  confirmation_token?)` read and draw grid lines through our add-on (`addon/`), as Tapir
  has grid commands only after 1.7.2. The length comes from the two points; the GDL
  parameters (the bubble text, for example) are checked by name and type against the
  Grid Tool defaults, which `include_parameters` lists. One Undo step for the batch,
  every line read back.
- `create_layout_subsets([{name, parent?, prefix?, numbering?}], port?, dry_run?,
  confirmation_token?)` adds up to 20 Layout Book subsets by Tapir 1.7.0
  `CreateLayoutSubset`, at the top of the book or inside an existing subset (`parent`
  by name or GUID). `prefix` turns on the subset's own ID prefix; `numbering` is one of
  `abc`, `ABC`, `1`, `01`, `001`, `0001`, `noID`. The rest comes from Archicad's subset
  defaults. A name already used under the same parent is refused. The read-back finds
  each subset in the Layout Book under its parent. `create_layouts` now takes an
  optional `subset` to put the new layouts in.
- `place_hotlinks([{source_path, origin: {x, y, z?}, floor_index, angle?, mirrored?,
  name?, single_story?}], port?, dry_run?, confirmation_token?)` places up to 20 hotlink
  modules by Tapir 1.7.0: one node per file (`CreateHotlinkNodes`, which reuses a node
  that already points at the same file, keeping its name and story settings) and then
  the instances (`CreateHotlinkInstances`). `source_path` is an absolute `.mod` or
  `.pln` path on the computer Archicad runs on; the MCP cannot check that it exists.
  `single_story` places only that story of the source. Other placement options keep the
  Hotlink tool defaults. The read-back checks each new element's type and story, and
  that its node is listed by `GetHotlinks`.
- `create_stairs([{start, end, floor_index, base_level, total_height?, flight_width?,
  risers?, favorite?}], port?, dry_run?, confirmation_token?)` adds up to 20 straight
  stairs by Tapir 1.7.0 `CreateStairs`, along the `start`-`end` baseline from
  `base_level` (absolute Z). What is left out comes from the Stair tool defaults or the
  favorite; Archicad's stair rules set riser and tread. Tapir returns no stair details,
  so after type and story the read-back checks the 3D box: it covers the baseline, starts
  at the base level and reaches the total height when one was given. Create on the story
  Archicad shows. Registry: **104 tools (29 reads, 75 writes/interactions)**.

### Live validation notes: sections and attribute values
Section markers inherit the Section tool defaults. On AC30 build 3001 BRA/Tapir 1.7.0,
an uninitialized/invalid marker returned APIERR_BADID. Explicitly applying an existing
Section favorite in the test project allowed creation to verify. The tool provides
recovery guidance and never changes defaults or retries automatically.
Attribute properties of type number/integer accept equivalent unitless ASCII decimal
read-back (1235 -> 1235.000). Strings, units, ambiguous locale separators and changed
numeric values remain strict. Receipt text preserves the actual Archicad response.
