# Object library replacement (issue #87)

Experimental, not approved for production until the live checklist below is complete.
The updated companion APX is required. Tapir 1.7.0 ModifyObjects cannot swap libInd.

## Workflow

1. Discover instances and explicitly select the test project/port.
2. Obtain the **full unique library ID** (main GUID and revision GUID) of an already
   loaded Object library part. Missing/duplicate IDs are rejected. Importing a new
   library is a separate operation, with its existing safeguards. To resolve the full
   ID, pass `target_index` from `list_library_parts` to the read-only inspector,
   omitting `target_unid`. An empty `guids` list reads only the target definition.
   All write previews still require the resolved full ID, never a bare index/name.
3. `inspect_object_replacements(guids, target_unid, port)` reads current libraries,
   dimensions, placement, story, angle, reflection, group/classifications and GDL
   parameters plus target defaults. It performs no mutation.
4. `replace_object_libraries(replacements, port)` prepares a preview. Each entry needs
   `guid`, `target_unid`, `source_mount` and `target_mount` (explicit XYZ).
5. Review the preview, including all parameter resets. Apply identical inputs with
   `dry_run=false`, the explicit port and the single-use confirmation token.
6. Keep the receipt. For a lost response, first inspect the actual object state and
   the prepared receipt; never replay the consumed token. No automatic retry occurs.

Mount points are measured in **metres in the final-sized object's local axes**, before
reflection and Z rotation. They are supplied separately for the two libraries; neither
origin nor bounding box is treated as a mounting reference. Reflection reverses local X
and is then rotated about Z. Story-relative mount Z is invariant and the home story is
preserved, hence world Z is invariant too. Nonuniform XY sizing is preserved through
the final A/B dimensions rather than by copying ratios between different nominal sizes.

## Explicit limitations

- Only standalone Objects; lamps, doors, windows, grid variations, hotlinks and owned
  objects are refused. One exact destination library per batch (up to 50 objects).
- Source and destination need readable positive A/B/ZZYZX dimensions.
- A/B/ZZYZX are preserved. **All other GDL parameters take destination defaults**,
  including arrays. The source memo and target defaults are disclosed in the preview.
  No implicit parameter mapping is attempted.
- The destination anchor is reset to origin (`fixPoint=-1`, zero offset), while
  translation compensates for the explicit mounting references. Angle, reflection,
  story and dimension values are preserved; ratios may change to preserve dimensions.
- GUID, destination library, dimensions, placement, angle, reflection, layer, group,
  classifications and mounting reference are reread. Properties and associations are
  not explicitly modified by the native mask, but their preservation is **not yet
  certified**. GDL property expressions may change when the library changes.
- Preview binds to the MCP session/project context, native boot ID and source
  modification stamp. State is reread before dispatch; stamps are checked again in
  the native Undo transaction. A native error aborts the entire Undo batch.
- Result receipts persist on disk; native boot IDs and confirmation tokens do not
  survive a restart. Restart is not permission to retry an unknown operation.
- No delete/recreate and no automatic project saving.

## Live acceptance checklist

Use only a disposable project. Record Archicad version/build/language and Tapir version.

- [ ] Wall sign, perpendicular sign and suspended object, each replaced in place.
- [ ] Different library origins/dimensions with **nonzero** explicit mount references.
- [ ] Rotation, reflection, nonuniform XY sizing, upper story and level offsets.
- [ ] Library identity, XYZ reference and dimensions reread after replacement.
- [ ] Source hotspot/offset changes produce the disclosed origin anchor behavior.
- [ ] GUID, layer, property values, classifications, groups and associations compared.
- [ ] One Undo restores the previous library, memo and complete placement for the batch.
- [ ] Stale/ambiguous/missing references refused and lost-result recovery inspected.
- [ ] No save and no mutation of production models.

Offline stubs are derived from our new C++ command implementation, not live captures.
Successful compilation or mocked geometry checks do not complete this checklist.

## References

- [API_ObjectType](https://graphisoft.github.io/archicad-api-devkit/struct_a_p_i___object_type.html)
- [Element Manager / ACAPI_Element_Change](https://graphisoft.github.io/archicad-api-devkit/group___element.html)
- [GDL mirror orientation](https://gdl.graphisoft.com/reference-guide/doors-and-windows/)
- Tapir 1.7.0 `ElementCreationCommands.cpp`, `ApplyObjectLampDetails`: dimension/memo
  reconciliation and the explicit limitation that ModifyObjects does not swap libInd.
