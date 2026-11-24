# Native associative level dimensions

`get_level_dimensions` reads native `LevelDimension` annotations, optionally filtering
by story or 1–100 GUIDs. `include_drawing=true` also asks the companion for the actual
drawn text primitives. Reads do not create, select or modify anything. A floor-plan
window must be active; other databases are refused. Scans are bounded to 5,000 levels.

`create_level_dimensions` previews/applies 1–20 native annotations in one Undo step.
Each item requires a model-space XY `point` (metres), `floor_index`, explicit `slab_guid`
and exact LevelDimension `favorite`, for example `COTA DE NÍVEL - PISO`. No text element,
GDL object or linear dimension is substituted. Obtain the authorized task's verified
backup first, using the normal same-working-PLN task workflow.

The default `reference="favorite", datum="favorite"` copies the favorite's native
element and retains its layer, marker, pens, font, text content (including multi-line
NA/NO autotext), datum and fixed text/leader offsets. Precision comes from the project
level-dimension preferences; these are read and never overwritten.

To explicitly replace the first note with a native live elevation autotext, use
`reference="top"` or `"bottom"`. `datum="project_zero"` explicitly requests project zero.
Secondary text stays as configured by the favorite. To avoid silently mixing datums,
project-zero override refuses a nonempty secondary custom note; select a single-note
favorite or preserve the original multi-note favorite/datum instead. Top/bottom with
stored-origin datum is refused because the API has no equivalent top/bottom keyword.

## Top versus reference plane

The native companion computes both absolute elevations from the actual slab:

```
top = story elevation + slab.level + slab.offsetFromTop
bottom = top - slab.thickness
```

`offsetFromTop` is the API's output-only reference-plane offset, so both Top and
Bottom reference planes are respected. Examples at story zero: a 2 cm finish on a
Bottom reference at 0 has top +0.02 m / bottom 0; a 1 cm finish has top +0.01 m.
At reference -0.20 m those tops become -0.18 and -0.19 m. Native `measuredLevel`
tracks the slab top; a bottom note uses the official bottom-elevation autotext,
not a static manually adjusted value.

## Guards and read-back

- Explicit port on apply and expiring one-use MCP preview token.
- Native plan binds session/project stamp, exact favorite style/content, actual slab
  elevations, precision and existing annotations. Native create recomputes this plan
  before starting the Undo operation and rejects stale snapshots.
- Slab must be local and on the requested story. Point must be inside its straight
  polygon and outside holes. Curved outlines are explicitly unsupported for now.
- Locked favorite layer is refused. Batch-internal duplicate points are refused.
- An annotation within 2 cm on the same slab/story is reused for inspection, never
  recreated or silently restyled. Multiple matches or a conflicting style require review.
- Native creation failures or in-scope native type/association/value/style mismatch
  return an Undo-operation error so the batch rolls back. Python then independently
  reads the resulting GUIDs, native type, parent, measured level, style/content and
  drawn text presence. Timeouts/missing results remain unknown; do not replay writes.

Verification scope is explicit in the receipt: native numeric value is checked;
the locale-formatted numbers inside arbitrary custom text are not parsed. Drawn text
is returned for coordinated visual acceptance. Existing reused annotations are not
modified if they fail verification.

## Deployment and pending live acceptance

Requires the matching companion with `GetLevelDimensions`, `PlanLevelDimensions` and
`CreateLevelDimensions`, plus an MCP process running this server revision. Recompile
the integrated companion and reload it as required by Archicad, then restart/reconnect
the MCP session to discover the Python tools. A successful source build does not add
tools to the currently running connection. Do not replace an active LAB Tools package
with an isolated candidate that omits other deployed capabilities.

No customer PLN is modified by the offline validation. Coordinate with Vitor before
any live placement. Test the exact favorite, +0.02/+0.01/-0.18/-0.19 examples, project
datum, native association after slab elevation/thickness changes, duplicate detection,
one-step Undo and visual appearance through MCP images. Archicad may impose native
creation/default/text behavior not exercised by mocks; live acceptance remains pending.

API sources: [LevelDimension](https://graphisoft.github.io/archicad-api-devkit/struct_a_p_i___level_dimension_type.html),
[element/reference-plane definitions](https://graphisoft.github.io/archicad-api-devkit/group___element.html),
[note autotexts](https://graphisoft.github.io/archicad-api-devkit/group___auto_text.html).
