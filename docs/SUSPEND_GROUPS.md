# Suspend Groups

`get_suspend_groups(port)` queries the native editing mode without changing selection.
`set_suspend_groups(suspended, port, dry_run=true, confirmation_token=null)` uses the
standard single-use preview/token protocol and receipt journal. Requires the companion
implementing `GetSuspendGroups` and `SetSuspendGroups`; Tapir alone is insufficient.

Suspend BEFORE previewing edits to grouped lamps. Keep `restore_suspended` from the
mode receipt, edit only the requested element GUIDs with the existing parameter tools,
then restore that value with a NEW mode preview/token even if the edit failed. Query
the mode first after an unknown outcome; never retry a consumed token. Verify that
the project identity still matches before restoring after an intervening edit.

This changes an editing mode, not membership: no ungroup/regroup, selection, additional
member edits or automatic saving. Mode restoration is explicit and is not Archicad
Undo. Existing model backup/save policies still apply to the separate GDL editing task.
The complete native project snapshot and previous mode are checked both when consuming
the MCP preview and immediately before the native change. Read-back is independent.

No automatic mode mutation is added to existing GDL tools. Invalid parameters, locked
layers, reservations and hotlinks remain subject to their existing guards. The reported
AC30 error -2130313112 is APIERR_BADPARS; grouping is not yet proven its only cause.

Validation is offline protocol mocks plus companion AC29/AC30 builds, not real grouped
editing. Live acceptance is pending: in a disposable project, group two lamps, record
membership and both parameter snapshots, suspend, edit one explicit GUID, verify only
the requested lamp changed, restore the original mode and verify memberships unchanged.
Repeat with a failed edit and with a stale preview. No client PLN or active installation
is used for this implementation's tests.

Official SDK references: [query](https://graphisoft.github.io/archicad-api-devkit/group___view.html)
and [change/restore](https://graphisoft.github.io/archicad-api-devkit/group___grouping.html).
