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
2. Technical lessons and pending items belong in GitHub. Until the historical log is
   migrated and validated, consult the existing Drive reference only in read-only mode:
   `<Drive>\02 - Empresarial\Projetos - Lab\Archicad\Archicad MCP\MCP Comunidade\Licoes-aprendidas.md`
   (`<Drive>` is `H:\Meu Drive` on one PC and may be `G:\Meu Drive` on the other).
   Do not append or renumber entries in Drive. Record new lessons (LA-xxx) and open
   items (P-xxx) in repository documentation, checking existing IDs. Use `docs/LICOES-APRENDIDAS.md` for new generic public entries once an authorized entry is needed; label its migration status explicitly, and never represent it as a complete historical register before validation.
   Migration must preserve history and exclude private information from this public repo.
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

## Test only what changed (Vitor, 29/10/2026)

Full test runs take too long. While you work, run only the tests that cover what you
changed: the test file of the tool you touched (`uv run pytest tests/unit/test_<tool>.py`),
plus the tests of any shared module you edited (connection, gateway, fake Archicad). In a
live test, check only the tools and behaviors the change touches. Run the full suite once
at the end (before you open or update a PR), when shared code changed, or when Vitor asks.
CI keeps running the full suite. Say in your report which tests you ran. This rule holds
for all of Vitor's projects (blocks, add-ons, MCPs).

## Rules

- Work on a branch and open a pull request to `main`. Claude merges a PR after its
  review, green CI and, when it touches Archicad behavior, a live test (Vitor's ok,
  11/10/2026). Codex never merges.
- Only report tests you actually ran. Say which Archicad version, build, language and
  Tapir version a live test used. Visual approval in Archicad is Vitor's.
- Vitor's current policy (27 October 2026): work in the project he requests, including
  saved/working projects. Do not require an untitled/test file or manual Save As.
  Before a requested editing task, preserve and verify an automatic _backup PLN
  in the project's `00 - Anteriores` folder (create it when missing; never a loose
  `Anteriores` folder, Vitor 05/11/2026). Keep only the newest backup per PLN:
  older `<stem>_backup*` files there are deleted (Vitor, 05/11/2026); include the current in-memory state, then save the result to the
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
- Never delete files on Vitor's computer except for the explicitly authorized, narrowly scoped verified PLN backup retention workflow above. This exception does not authorize deleting technical logs, unrelated backups or other project files.

## Repository and storage policy (28 November 2026)

- GitHub is the canonical source for code, technical documentation, approved decisions, lessons, pending items, tests and development history. Conversation memory is evidence, not authority.
- Before editing, verify the repository, target ref, current commit and existing changes. In a local clone, check `git status`, `origin` and `git fetch`; preserve local and remote work. For connector-only documentation work, verify the remote ref and file version instead; do not claim local checks. Use an isolated checkout outside synced Drive folders for local development and tests. Reuse existing paths and files.
- Google Drive is reserved for architectural projects, authorized deliveries, release snapshots and authorized backups. Never use it as an active development checkout or write new permanent development logs there. Distribution receipts, versioned source snapshots and delivery maps remain permitted in their authorized delivery locations; they are not canonical development sources.
- Preserve historical external references and files as read-only until an approved migration is validated. Record new technical lessons and pending items in the appropriate GitHub repository; retain identifiers, dates, reasons, evidence and status. Do not claim an unmigrated register exists in GitHub. Do not copy private rules, client data or credentials into public repositories.
- Review the diff and relevant checks before authorized commits/pushes; verify the remote commit and report branch, changed files, tests, synchronization and blockers. Distinguish code changes, commits, builds, deliveries and actual installation.
- No destructive Git operations, overwrite of collaborators' work, merge, deployment, publication or deletion without applicable authorization. Existing authorized project backup/save and distribution contracts remain intact.
- Governance-only reviews do not authorize builds, releases, installations, delivery or changes to revision metadata. If CI requires a new material revision even for documentation, report the blocker and obtain applicable authorization for the revision; do not bypass the revision check.

## Material revisions

Read `docs/DISTRIBUTION.md` before preparing a delivery. Change the single revision
in `distribution.json` when published material changes; generate names with
`tools/distribution.py`. Preserve old revisions and keep Main/test and Archicad majors
separate. Deliver verified APX and versioned source snapshots tied to the originating Git commit
only to the authorized Drive folder; never include credentials, venv or a working clone. Do not modify LAB Blocos.
