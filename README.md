# archicad-mcp-aberto

Open source [MCP](https://modelcontextprotocol.io) server that lets AI assistants
(Claude, Codex, Cursor and others) work with a running Archicad: read the model and preview or create straight Basic walls safely.

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

Phase 1 foundation, pre-alpha. Nine **read-only** tools plus safe wall creation:

| Tool | What it does | Needs Tapir |
|---|---|---|
| `discover_archicad` | Open instances: port, version, Tapir state, project name, counts | for the project name |
| `list_elements` | Element GUIDs, by type, paged | no |
| `get_selection` | Current selection, without changing it | no |
| `list_properties` | Property definitions | no |
| `get_properties` | Property values, with per-item errors | no |
| `tapir_status` | Whether Tapir is loaded in each instance | yes |
| `get_project_info` | Project name, path, Teamwork state | yes |
| `get_stories` | Stories and levels | yes |
| `get_element_details` | BIM details; floor plan polygons only on request | yes |
| `create_walls` | Preview or apply up to 20 straight Basic walls, with per-wall receipts | yes |

Tested so far against a simulated Archicad (unit tests). The tools were first tested
live on Archicad 29 build 3000 (Windows) with Tapir 1.7.0 in the bridge this project
grew from. A public matrix of tested versions comes with the live tests.

## Install

Requires [uv](https://docs.astral.sh/uv/). Until the first release, run from a clone:

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
1. Safe writes: wall and slab creation started; editing, objects and Undo remain. **← here**
2. Command gateway (every official and Tapir command) and batch scripts; `.mcpb` bundle.
3. Documentation tools: dimensions, views, publishing, view capture; GDL and libraries.
4. First public release.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). You do not need Archicad to contribute: the
unit tests run against a simulated Archicad.

## License

[MIT](LICENSE)

- Exact floor-plan polygon duplicates within each element are removed (same vertex order, 1e-9 m tolerance); `notes` reports the removed count. Different polygons are preserved.
