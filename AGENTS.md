# Instructions for AI agents (Codex, Claude Code and others)

This file is shared by every coding agent working on this repository. `CLAUDE.md` only
points here, so keep all agent instructions in this one file.

## Who this is for

The maintainer is Vitor, an architect in Brazil. **Talk to him in Brazilian Portuguese**,
directly and in plain words. Code, identifiers, commit messages, PR text and the English
README stay in English so the community can contribute.

## What this project is

An open source (MIT) MCP server for Archicad. It talks to a running Archicad through the
official JSON API on localhost (ports 19723 to 19743) and to the Tapir add-on through
`API.ExecuteAddOnCommand`. It exists because Graphisoft's own MCP is beta only in
Archicad 30 Collaborate and Max. Architecture decisions and the comparison with other
projects: https://claude.ai/artifact/B2FsgTjNSA9HM8aMvXHWEz

## Before you start, read

1. `docs/ESTADO.md`: where the work stopped and what comes next. Update it before you
   finish a session, so the next agent (Codex or Claude) can continue.
2. The lessons log on Vitor's Google Drive, when you can reach it:
   `<Drive>\02 - Empresarial\Projetos - Lab\Archicad\Archicad MCP\MCP Comunidade\Licoes-aprendidas.md`
   (`<Drive>` is `H:\Meu Drive` on one PC and may be `G:\Meu Drive` on the other).
   Add new lessons (LA-xxx) and open items (P-xxx) at the end; never renumber; re-read
   the file right before saving, because other agents edit it too.
3. `CONTRIBUTING.md` for where code goes and the rules for a tool.
4. `docs/FILA.md`: Codex's task queue, kept by Claude. When Vitor says "faça as tarefas
   de docs/FILA.md", follow the rules at the top of that file.

## Commands

```bash
uv sync
uv run pytest          # unit tests against tests/unit/fake_archicad.py
uv run ruff check .
uv run ruff format .
uv run archicad-mcp-aberto   # the MCP server (stdio)
```

Do not create the virtual environment inside Google Drive. Work from a clone on a local
disk.

## Rules

- Work on a branch and open a pull request to `main`. Claude merges a PR after its
  review, green CI and, when it touches Archicad behavior, a live test (Vitor's ok,
  11/10/2026). Codex never merges.
- Only report tests you actually ran. Say which Archicad version, build, language and
  Tapir version a live test used. Visual approval in Archicad is Vitor's.
- Vitor's current policy (27 October 2026): work in the project he requests, including
  saved/working projects. Do not require an untitled/test file or manual Save As.
  Before a requested editing task, preserve and verify an automatic _backup PLN
  in Anteriores; include the current in-memory state, then save the result to the
  SAME working PLN at task completion. No automatic revision bump. His request
  authorizes this backup/save workflow; do not ask for it repeatedly. Do not save
  for read-only operations, silently switch projects or blindly retry unknown writes.
- With several Archicad instances open, never pick one: use `resolve_port`.
- Lengths in meters, angles in radians.
- When the fake Archicad learns a command, copy the response shape from a real Archicad.
  A wrong key in the fake once hid a bug (`propertyIds`, see CHANGELOG).
- A missing native command may go straight into our own add-on in `addon/` (Vitor,
  21/10/2026: "não quero ficar dependendo de update do Tapir"). Also send the same
  command to Tapir upstream as a suggestion, so it can replace ours later. The add-on
  needs a Graphisoft-issued MDID.
- Never delete files on Vitor's computer.

## Material revisions

Read `docs/DISTRIBUTION.md` before preparing a delivery. Change the single revision
in `distribution.json` when published material changes; generate names with
`tools/distribution.py`. Preserve old revisions and keep Main/test and Archicad majors
separate. Deliver verified APX and corresponding source copies to the authorized Drive
folder; never include credentials, venv or a working clone. Do not modify LAB Blocos.
