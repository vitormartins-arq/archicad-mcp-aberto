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

Pre-alpha. Phase 1 is nearly complete: **22 tools**, with **13 read-only** tools and
**9 write** tools. Writes preview by default and require a single-use confirmation token
and explicit port to apply. No tool saves the project. Rotation, GDL parameter editing
and wall editing are the next queued additions; live Undo validation remains pending.

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
| `list_library_parts` | Read | Loaded part names/GUIDs/types, with partial-inventory diagnostics | yes |
| `create_walls` | Write | Up to 20 straight Basic walls | yes |
| `create_slabs` | Write | Up to 20 simple polygon slabs | yes |
| `create_columns` | Write | Up to 20 rectangular/circular columns | yes |
| `create_objects` | Write | Up to 20 library objects by name, position and angle | yes |
| `create_beams` | Write | Up to 20 straight rectangular beams | yes |
| `create_zones` | Write | Up to 20 manually bounded polygon zones | yes |
| `move_elements` | Write | Move up to 50 elements without copying; check displaced boxes | yes |
| `set_property_values` | Write | Up to 100 scalar property changes, read back after apply | no |
| `delete_elements` | Write | Up to 50 editable elements, only in untitled test projects | yes |

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

## Safety rules

- With several instances open, nothing runs without an explicit target. The server
  never picks the first port.
- "Busy" (error 4001) is reported as busy, not as a missing add-on.
- Heavy reads (floor plan polygons) only run when asked for.
- `create_walls` dry-runs by default. Review the plan with the user before applying;
  writes have per-wall receipts and a geometry check after applying. No tool saves the project.

## Wall creation

`create_walls` accepts `walls`, an optional `port`, `dry_run` (default `true`), and
`confirmation_token`. This initial scope supports straight Basic walls only. Lengths
are metres. Each wall needs `start`, `end`, `floor_index`, `height` and `thickness`:

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

Optional wall settings are `bottom_offset` (relative to the chosen story), `offset`
and `reference_line` (`Outside`, `Center` or `Inside`). New walls inherit Archicad's
current default layer and building material.

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
   guarded deletion delivered. Nearly complete; rotation, GDL/wall editing and live Undo
   validation remain. **← here**
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

- `find_elements` filters by `element_type`, `floor_index`, `layer_index` and optional `property_guid`/`operator`/`value`. Operators: `equal`, case-sensitive `contains`, `greater`, `less`. It returns total matches, offset, a page of up to 500 element IDs and read errors. Missing properties are refused; unavailable values do not match. Type filtering precedes detail reads, and story/layer filtering precedes property reads, in batches of 100.

- `delete_elements` previews up to 50 GUIDs and applies only in an untitled test project (`isUntitled=true` from Tapir). It lists type/story/layer, refuses missing, hotlinked or non-editable elements, requires explicit port and a single-use token, writes per-element receipts and verifies absence. Uses Tapir `DeleteElements` and `FilterElements(IsEditable)`; `API.DeleteElements` is not an official JSON API command. Never saves, unlocks or automatically retries. Owned subelements may also be removed by Archicad.

- Existing-element previews show `floorIndex`/`floorName` and `layerIndex`/`layerName`. Layer names are fetched once per preview using Tapir GetAttributesByType(Layer); missing names are null. Renaming a story or layer does not invalidate the confirmation token; indices and story levels still do.

- `create_beams` previews up to 20 straight rectangular beams: `start`/`end` `{x,y}`, `floor_index`, absolute project `level`, positive `width`/`height`, all metres. Centered section, no slant/rotation/curves, independent width/height. Uses the shared single-use token, explicit port, durable per-beam receipts and timeout. Checks type/story/endpoints/absolute and story-relative level/section. Layer/material defaults are inherited; custom profiles fail verification. GetDetailsOfElements reports the first segment, so use a basic single-segment default for live testing. Source-derived Tapir 1.7.0 fixture, not live captured.

- `create_zones` previews up to 20 manually bounded zones with simple `outline` points `{x,y}` in metres, nonblank `name`/`number` strings and `floor_index`. Polygon validation matches slabs: 3–200 vertices, no holes/arcs, no repeated vertices or intersections. Explicitly closed outlines are normalized. Uses shared token/port/receipts/timeout and checks type/story/name/number/manual contour (vertex rotation/reversal allowed). Category, stamp and base defaults are inherited. Source-confirmed Tapir CreateZones; synthetic fixture, not live captured.

- `list_library_parts` reads available part GUIDs/indices/names/types using Tapir `GetAvailableLibraryParts` (registered since 1.5.0). Optional case-insensitive `name_contains`, `offset`, `limit` up to 500; partial inventory metadata is preserved. `create_objects` refuses unknown names with a complete inventory and ambiguous names in dry run. With a partial inventory, only missing items are marked `unconfirmed` with a warning; native creation resolves them per item at apply. It rechecks before applying; the selected part GUID is bound into the token. See [the source investigation](docs/LIBRARY_PARTS.md) for each confirmed command and the distinction from GetLibraries.

- `rotate_elements` previews up to 50 `rotations` (`guid`, `center:{x,y}` in metres, `angle` in radians). No copies/saves/unlocking. Refuses nonexistent/hotlinked/non-editable elements. Shared confirmation, receipts and timeout. Verifies endpoints or origin/angle where available; box-only verification supports multiples of pi/2 within 1 mm, because rotating an AABB cannot predict arbitrary shapes at other angles.

- `get_gdl_parameters` reads up to 100 Object GUIDs, preserving GDL types, dimensions, flags, values and per-item errors. `set_gdl_parameters` previews up to 100 `{element_guid,name,value}` changes to existing scalar parameters, then verifies read-back. Rejects arrays/dictionaries, hidden/fixed/disabled/locked parameters, hotlinks and locked elements. Strings, booleans and finite numeric values must match the parameter type; LightSwitch booleans map to On/Off. Metres/radians; token, explicit port, receipts and timeout shared; never saves.
