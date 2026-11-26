# Floor surface RGB backgrounds — candidate

Requires the private R35 companion on Archicad 30. Not live validated yet; do not
apply to client projects until disposable-project visual, Undo and reopen checks pass.

`get_floor_surface_backgrounds(guids, port)` reads effective top-surface RGB,
native hatch settings, the complete pagination transform, geometry and overrides.
`set_floor_surface_backgrounds(guids, scope_id, port, view_guid?, task_token?,
dry_run=true, confirmation_token?)` previews first. Supply a fresh UUID as scope,
explicit Slab GUIDs and an explicit port for apply. Saved projects require an active,
verified `begin_model_task` checkpoint for that project/session. Reuse exactly the
same arguments with the returned confirmation token; tokens are single-use.

The implementation copies RGB into native cover-background-only graphic override
rules, scopes them using a newly created custom string property assigned only to
the requested Slabs, and clones the active combination without editing original
rules. No shared pen is changed, no overlay polygon is created, and Element IDs
are preserved. Generic surface criteria are not used because they can match a
Slab's sides/bottom rather than its top. Original rules remain in their original order.

Hatch, foreground pen, origin, matrix, scale, contours, holes and arcs are checked
against native snapshots. Effective RGB is read back, along with other effective
overrides. Top surfaces come from an explicit override or a Basic Slab's building
material; composite fallback is refused pending validation.

**Color is a snapshot.** Explicitly synchronize again after changing the top surface
or its RGB; automatic color tracking is not claimed. Each operation creates fresh
metadata; cleanup/reuse is not implemented. Copying a Slab can copy its scoped tag.

Optional `view_guid` persists only the target view's override-combination name;
all other readable view settings are compared before/after. Without it, only the
active floor-plan representation changes. The saved-view step is separate from the
native transaction; do not claim that one Undo restores both. No PLN is saved by
this tool. Finish the verified task using the existing save policy.

On unknown or partial results, inspect the receipt and current state. Do not blindly
retry: native artifacts might already exist. The receipt retains native stages/SDK
errors, created identifiers and any saved-view write attempt.

Required live checks: rotated hatch with displaced origin and nonidentity matrix,
hole/arc, multiple colors, untouched unselected elements, surface change and explicit
resync, exact preservation, visual MCP capture, Undo and save/reopen. Use a disposable
PLN. WG Formosa and Template are not test fixtures.
