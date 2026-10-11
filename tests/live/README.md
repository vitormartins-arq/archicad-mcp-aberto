# Manual live smoke

Run only on an explicitly chosen test project on Vitor's PC. Importing the script
or running unit tests does not connect to Archicad. Codex tested this runner only
against the fake Archicad; live execution and visual approval belong to the operator.

```bash
uv run python tests/live/smoke.py --port 19723
uv run python tests/live/smoke.py --port 19723 --write
```

`--port` is mandatory. The default mode only reads discovery, project, stories,
elements and details of up to five walls, including `floorPlanPolygons`. A missing
polygon is recorded as returned by the read tool; it is not a failed smoke by itself.

`--write` requires `isUntitled=true` from the project on that port. A project with
a name, a missing flag or an unconfirmed flag is refused before writing. Open the
floor plan in the unsaved test project and obtain Vitor's approval for this live run.
The runner rechecks the untitled flag before previews and applications.

It reads all element floor-plan bounding boxes in batches, chooses a corner beyond
their maximum X/Y with a 10 m margin, and records it in the report. Empty projects
use (20, 20) m. If any box is unavailable or invalid, writing stops. Bounds follow
the active floor-plan view; check that view and the reported corner visually.
The runner uses story 0 when available, otherwise the first reported story.

It previews/applies two 4 m / 3 m walls in an L (height 3 m, thickness 0.20 m), then
one separate 4 by 3 m slab (thickness 0.20 m, absolute top level at the story level).
It then creates one separate rectangular column (0.30 by 0.50 m, height 3 m,
base at the story level). Each batch has a fresh single-use preview token and verified per-element receipts.
Inherited tool defaults may produce verification failures; the report retains them.
A failure or unknown outcome stops subsequent writes without retry or rollback.

**The runner never saves, deletes elements or runs Undo.** Inspect the result and
use manual Undo to revert successful batches (column, slab, then walls). Partial writes must
be inspected before undoing or attempting a new run; an unknown outcome can already
have created elements.

JSON reports default to `~/.archicad-mcp-aberto/smoke`, with unique filenames, UTC
start/finish times, reads, write previews/receipts and errors. They are updated before
and after each batch. Use `--report-dir <outside-folder>` to change the directory;
paths inside the repository are refused. Tool receipts also use their normal local
receipt folder. Exit status is 0 for a passed smoke and 1 for a failed smoke; argument
errors exit with 2. Keep the JSON report when reporting a live result, including the
Archicad version/build/language and Tapir version in discovery.

The bounding-box response used in unit tests is documentation-derived, not a live
capture: [Graphisoft Python API](https://archicadapi.graphisoft.com/archicadPythonPackage/archicad.html).

```bash
uv run pytest tests/unit/test_live_smoke.py
```
