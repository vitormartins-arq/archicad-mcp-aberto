# Experimental save and close

`save_and_close_project(port=..., dry_run=true)` previews exactly one saved standalone
PLN. Repeat the same explicit port with `dry_run=false` and its `confirmation_token`
to apply. A path/session/epoch/modification stamp and disk-file fingerprint bind the
preview. Untitled, Teamwork, missing files and old companion revisions are refused.

The updated companion must be installed separately before this command is usable.
This change does not install it, reload a running MCP or close any real project.

## Protocol

1. The server writes its prepared receipt before any native operation.
2. `PrepareProjectClose` validates the original identity, saves the SAME working PLN
   using the existing native save helper, reads the identity back and checks the file.
   It issues a native one-use proof, bound to that context, size and last-write time,
   expiring after ten minutes. No new revision or archival move is performed.
3. The server reads the context again, verifies nonempty file size, hashes the saved
   file and rechecks its fingerprint and context. It persists the save receipt before
   requesting closure. Any failed save/verification aborts closure.
4. `ClosePreparedProject` consumes the proof first and rechecks identity, modification
   stamp and saved-file metadata immediately before calling the native Close function.
   Any change, modal/API refusal or expired proof stops the operation. No retry, input
   simulation, process kill, application quit or fallback to another port is allowed.
5. Success requires native Close to return NoError AND a subsequent native Project
   query to return APIERR_NOPLAN. A timeout/disconnect remains **unknown**, even if the
   endpoint disappears. Keep the prepared/saved/result receipts and inspect manually.

The normal JSON request scheduling must reject busy/modal states. This implementation
does not inspect or dismiss dialogs, nor does it claim a separate modal detector.
There is no public unsaved-state flag in the existing save-context response, so the
tool always saves the same path; it never guesses that an already saved project is
clean and never creates an unnecessary R/REV to close it.

## API limitation

The [Graphisoft AC30 Project Operations reference](https://graphisoft.github.io/archicad-api-devkit/group___project_operation.html)
and installed AC30 DevKit declare `ACAPI_ProjectOperation_Close`, but explicitly mark
it **not for public use**. It is a complete operation: no undoable/non-undoable wrapper,
no notification callback; another running add-on may cause refusal. This implementation
therefore remains experimental until controlled acceptance proves it works in this
command context. Compilation alone is not runtime support. It closes the project,
not necessarily the Archicad application/process.

## Controlled manual acceptance (not yet performed)

Coordinate the exact target with Vitor first; do not use the Pura/WG/Rose working
files as an unannounced test. With the new matching MCP/companion in a disposable PLN:

- Preview and confirm nothing was saved/closed. Change the model after preview and
  confirm stale apply is refused. Check other open instances remain untouched.
- With an authorized fresh preview, apply and confirm the current in-memory changes
  are saved to the same PLN, no revision is created, the project closes, and the
  receipt confirms native no-open-project read-back. Reopen it and check the changes.
- Test save failure, active modal, close refusal and interrupted connection; ensure
  closure is not retried and a disconnect never appears as verified success.

Offline tests use protocol mocks and temporary files, not captured native responses
for the new commands. They verify orchestration/refusal/receipts, not Archicad behavior.
