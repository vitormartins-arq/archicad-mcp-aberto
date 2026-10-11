# Contributing

Issues and pull requests are welcome in English or Portuguese.

## Setup

```bash
uv sync
uv run pytest          # unit tests, no Archicad needed
uv run ruff check .
```

## Where things go

| Folder | What lives there |
|---|---|
| `src/archicad_mcp_aberto/connection/` | HTTP client, discovery, error mapping |
| `src/archicad_mcp_aberto/tools/` | Tool logic, plain async functions taking an `ArchicadClient` |
| `src/archicad_mcp_aberto/server.py` | MCP registration only |
| `tests/unit/` | Tests against `fake_archicad.py`; these run in CI |
| `tests/live/` | Tests against a real Archicad; run locally with `-m live` |
| `addon/` | Native C++ code, only for gaps Tapir cannot cover |

## Rules for a tool

1. Keep the logic in `tools/` and test it with the fake Archicad. If the fake does not
   know a command yet, add it there with a response copied from a real Archicad.
2. Lengths in meters, angles in radians. Say so in the docstring when it matters.
3. Never pick an instance when several are open: use `resolve_port`.
4. Read tools are annotated `readOnlyHint`. Write tools must dry-run by default,
   report results per element and check the model after writing.
5. A new Tapir command belongs upstream in Tapir first. Native code in `addon/` needs
   an issue explaining why Tapir cannot do it.
6. Only report what you tested. Say which Archicad version, build, OS and Tapir
   version you used in the PR.

## Live tests

Open a **test project you can lose**, then run `uv run pytest tests/live -m live`.
Add your result to the version matrix in the PR description.
