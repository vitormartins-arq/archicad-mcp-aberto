# Native PLN Save As and revision archival

`save_project_as(destination_path, port)` previews an explicit absolute PLN destination.
`save_next_project_revision(port)` previews the next revision in the current folder and
the previous file's destination in its `Anteriores` subfolder. Both default to dry run;
apply identical inputs with `dry_run=false`, the explicit port and single-use token.
These are the only tools that explicitly save the project. Other model writes do not save.

For example `Example_R04.pln` becomes `Example_R05.pln`; after verification the old
file moves to `Anteriores/Example_R04.pln`. The new file contains the current in-memory
model, including unsaved changes, through `ACAPI_ProjectOperation_Save` with
`API_FileSavePars.fileTypeID=APIFType_PlanFile` and an explicit `IO::Location`.
This is not a disk copy. Save runs directly on Archicad's main thread, outside any
Undo/non-Undo command wrapper. Saving and filesystem archival have no Archicad Undo.

The last `_R04`, `-R04`, ` R04` or corresponding `REV` token is incremented, keeping
its label and numeric width, plus any trailing description (for example,
`Example_R05_TEST.pln` becomes `Example_R06_TEST.pln`). Without one, append `_R01`. Existing matching revisions
in both folders advance the number; do not fill gaps or replace existing files.
An archive-name collision gets `__archive_001`, etc.; existing archives stay intact.

## Safety and recovery

- Preview binds port, native add-on session, project open/close epoch, project path,
  modification stamp, project kind, paths and old-file metadata. A changed context,
  edited model, reconnect, newly occupied path or changed old file requires a new plan.
- The native command checks the context again immediately before dispatch. Project
  lifecycle events invalidate the epoch; the stamp is a decimal string to preserve UInt64.
- Persist a prepared receipt and consume the token before the native call. A native
  error/timeout has unknown outcome: never repeat it or archive automatically. Use
  `inspect_project_save(destination_path, port)` plus the receipt to inspect, without writing.
- Verify native current project path and same session/epoch, and a nonempty regular PLN,
  before moving the old file. This verifies presence/path, not that a PLN can be reopened
  or semantically matches the entire model. Final acceptance requires a real save/reopen.
- Old-file metadata must match the preview before moving. Archive move refuses an
  occupied destination. If archival fails, retain the old file and report save success
  separately from archival failure; never delete the new saved revision to roll back.
- Teamwork is refused. Next revision requires an already saved standalone PLN; an
  untitled project first needs an explicit destination via `save_project_as`.
- Server and Archicad must run on the same computer and share the file paths. No remote
  filesystem guessing, directory creation for Save As, model switching or automatic retries.
- Symlinks/junctions and ambiguous paths are refused by the Python planner. Local/cloud
  synced ordinary files still depend on filesystem permissions, sync and locks.
- The native API has **no atomic no-overwrite flag**. Destination existence is checked
  in preview, apply and native dispatch, but a noncooperating external writer can race
  the last check and native Save. Reserve a unique destination; do not write it elsewhere
  concurrently. Do not describe this as an atomic save/no-clobber guarantee.

## Validation and manual live test

Offline tests simulate the native boundary and use temporary files. They cover current
in-memory content versus old disk content, stale identities, single-use tokens, archive
collisions, changed/empty/missing results, native timeout and archive permission failure.
They do not execute Archicad or validate SDK runtime behavior. No local APX was compiled,
installed or loaded during this change; no live Archicad was queried.

- [ ] Live test: after coordinating a convenient time, load the rebuilt companion add-on
  **only in a disposable project**. Save a standalone `Example_R04.pln` in a test folder,
  edit the model without saving, preview/apply next revision, check R05 is current and
  contains that edit, and reopen both files to confirm old R04 content in `Anteriores`.
- [ ] Confirm read-only/locked/occupied destinations fail without replacing files, an
  edit after preview refuses apply, and an existing archive is preserved under collision.
- [ ] Confirm a failed archive leaves both the saved new PLN and the old PLN recoverable.
  Do not simulate timeouts by interrupting a real user's production save.

No live test is marked complete. Native build/runtime validation is pending.

## Live validation on 27 October 2026 (Brazil)

Authorized disposable PLN in Downloads; Archicad 30 build 3001 BRA, Tapir 1.7.3,
LAB Tools R12 combined native companion R11 (private source 16d33d4, importing
public strict save implementation 74f026b). Invoked the public Python tool function
through the isolated terminal checkout; this does not claim the running AI client's
MCP server configuration was upgraded.

Verified native context, next revision with a trailing test suffix, native Save As,
new nonempty PLN/current project path, same session/epoch, and archival after save.
The archived old PLN's SHA-256 matched the pre-save original exactly. An occupied
destination was rejected in preview without writing. No production project was used.

The preview exposed a suffix naming bug (R05_TEST previously appended R01), fixed
before writing; 2794 full offline tests and Ruff/format passed after the fix.
Reopening both PLNs, checking an intentional unsaved model edit and exercising native
failure/permission paths live remain pending. These results validate the combined
LAB Tools companion, not an independent loading test of the standalone public APX.
