# archicad-mcp-aberto

Open source [MCP](https://modelcontextprotocol.io) server that lets AI assistants
(Claude, Codex, Cursor and others) work with a running Archicad: read the model today,
and create and edit elements safely in the next phases.

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

Phase 0, pre-alpha. Nine **read-only** tools:

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
- Write tools (next phase) will dry-run by default, keep a receipt of every write and
  check the result after applying.

## Roadmap

0. Foundation: connection, discovery, read tools, simulated Archicad, CI. **← here**
1. Safe writes: walls, slabs, objects, properties, selection; real Undo tests.
2. Command gateway (every official and Tapir command) and batch scripts; `.mcpb` bundle.
3. Documentation tools: dimensions, views, publishing, view capture; GDL and libraries.
4. First public release.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). You do not need Archicad to contribute: the
unit tests run against a simulated Archicad.

## License

[MIT](LICENSE)
