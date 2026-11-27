# Visual completion of project/model edits

An API response, GUID, coordinate, bounding box or numeric readback does not establish
correct appearance. Every MCP project/model write is guarded at registration through
`VisualReviewMCP`, including extensions registered later by a private server. Pure reads
and temporary view/session actions do not trigger redundant capture. Low-level Python
tool functions retain their numeric contracts; this is an MCP-boundary completion gate.

## What is implemented

- All 106 current `destructiveHint` registrations inherit the guard automatically.
  `visual_review_coverage` lists the actual registry, policies and coverage; it includes
  private extensions, without requiring public knowledge of their implementation.
- Dry runs only add an inspection plan. For multi-item changes, first apply a small
  sample of the same operation and inspect it. A batch dispatch is refused until an
  approved sample exists for the same project and current modification stamp. Changes
  between sample and batch require a fresh assessment. Preview the remainder afresh.
- Before an apply, a durable local pending receipt is written. After apply, numeric
  results remain available as `model_verification_status`/the original model receipt.
  A previously `verified` top-level MCP result becomes `awaiting_visual_review`, with
  `task_complete:false` and a review ID. Do not report the task complete at this point.
- Actual post-edit images are returned inline. Auto capture tries existing native 2D,
  window capture, then native 3D capabilities; data/layout/navigation contexts prefer
  the actual window. No native commands are invented and no UI automation is invoked.
  Only implemented calls are attempted; failures are preserved per capability.
- Captures are bounded and decoded, not accepted from a PNG prefix alone. Checks reject
  corrupt/truncated, tiny, unsupported and uniform/low-contrast images. Files are hashed.
  Project identity and modification stamp are checked across capture and assessment.
- `finish_model_task`, `save_project_as`, and `save_next_project_revision` refuse final
  saving while reviews for this native project/session remain incomplete. The automatic
  pre-task checkpoint is explicitly exempt: it precedes edits and is not completion.
  The OBJ preparation stage creates only its preview/request and is also explicit.
- Unknown writes are not retried. `reconcile_visual_review` calls an existing explicitly
  read-only getter on the same port and stores the actual readback. The assistant must
  compare it with the intended state, inspect images, and record a concrete numeric
  reconciliation observation. The server does not infer that comparison from raw JSON.

## Inspection workflow

1. Apply a single item/small initial sample using the original preview/token flow.
   LOOK at the inline image. A capture is a candidate, never automatic approval.
2. If necessary activate the correct story/view/layout through existing MCP tools.
   Call `capture_visual_review(review_ids, port, source, ...)`:
   - `source="plan"` uses GetPlanWindowImage and an optional model-space `zoom`, restored
     after capture. `element_guids` instead reads real official 2D boxes and adds a
     neighbourhood margin. This does not require WindowZoom or SetZoom. Do not combine
     element framing with explicit zoom. Split different floors/areas into separate images.
   - `source="window"` uses the existing window-image tool. It cannot apply a requested
     model-space zoom; fallback evidence says so. Navigation must be handled separately.
   - `source="3d"` uses the current native 3D image, without changing the camera. Frame
     a correct 3D view using existing scene/camera tools before taking this evidence.
3. Inspect the actual changed context at readable scale. Labels require their object,
   mounting face, reading direction and neighbouring symbols. Layouts require updated
   drawings and the actual sheet/PDF. Data-only changes require the relevant schedule,
   dialog or documentation representation; an unrelated plan is not evidence.
4. Call `review_visual_result` with the evidence ID, a concrete observation, and explicit
   context/framing/readability/coverage assessments. Failed flags cannot pass. If wrong,
   use `needs_correction`, correct, recapture and assess again. Several pending edits can
   share one contextual capture when it actually covers all of them. Do not request one
   picture per element when one composition covers a batch.
5. With the sample approved, preview/apply the remaining batch. Inspect final coverage,
   including areas omitted by the sample. Repeat steps 2–4 as needed, then finish/save.
   Pure reads and dry runs do not create pictures or completion obligations.

## Blockers and limits

The server has no vision model. Pixel/identity checks cannot recognize an unrelated
room, cropped target, unreadable text, UI-only frame or semantically empty drawing.
The assistant must actually look and evaluate these. Recorded approval is explicitly
an `assistant_reported_visual_assessment`, not independent machine or user approval.
Window captures, images/PDFs and receipts remain local and may contain project data;
never publish them as generic test fixtures.

No adequate capture means the task is **incomplete**, with a recorded blocker. Try a
different available MCP capture/framing capability and diagnose the failure. Do not
claim correctness from hotspot positions, numerical results or a successful image API.
Computer Use is not a fallback without the user's applicable authorization. A missing
identity capability can still return a useful candidate window image, but cannot pass
the completion gate. Capturing the wrong view does not fix missing framing.

Unknown/failed numeric results require actual reconciliation in addition to images.
Never repeat a timed-out write merely to produce a fresh receipt. A restart reloads
unresolved local receipts. Explicit recapture can resume an old MCP client review only
for the same native project/session. Corrupt pending receipts block final completion
instead of being silently discarded. Receipts/images are in
`~/.archicad-mcp-aberto/visual-reviews`; model writes are refused if their pre-dispatch
receipt cannot be stored. Review JSON includes the original numeric receipt.

The gate does not prevent a user or another application from editing/saving outside
this server, and it cannot prove an assistant truthfully inspected a displayed image.
It makes missing evidence explicit, links it to the actual state, and refuses premature
completion through the guarded MCP path. Annotation accuracy remains a maintainer
responsibility; coverage tests enforce current project/model registrations.

## Validation status

Tests use synthetic PNGs and simulated tool responses, never private/live model data.
They cover actual FastMCP result conversion, pending numeric success, inline images,
alternative captures, blank/invalid images, wrong-context flags, sample gating,
corrections, stale/tampered evidence, durable restart state, real ambiguous-target
resolution, readback reconciliation and public/private registration inheritance.
Offline tests are not real Archicad visual acceptance. Local installation and loading
in a fresh MCP process must be reported separately from an already running connection.

## Capture context per attempt

Each capture capability now waits for a bounded exact context stabilization and uses
that context as its own before/after boundary. A native export discarded for a changed
stamp must not poison a subsequent stable window capture by sharing its earlier stamp.
Project/session identity changes are never rebased. If a source changes the stamp during
its own capture, that image is still discarded; if context never settles, no capture is
accepted. Assessment continues to require the exact current evidence context and file hash.

Failure receipts record changed context fields and private before/after values for
troubleshooting. Those runtime receipts may contain project paths and must not be
published as fixtures. This change does not prove that an observed stamp increment was
only a redraw: no delta allowance, ignored stamp or numeric-only visual approval exists.

Windows window capture now copies the existing surface with BitBlt instead of sending
PrintWindow, which can force regeneration and advance Archicad's project stamp. The
exact context check stays enabled. The target must be visible; stale/occluded display
is not acceptable evidence, and the assistant must still inspect actual context and
legibility. A failed copy is refused rather than falling back to forced repaint.


## Superseded corrections

An incorrect/reverted attempt must never be marked passed just to clear the save gate.
Use `supersede_visual_reviews(review_ids, replacement_review_id, observation, port)`:

1. Apply the actual correction using its existing preview/token and receipt flow.
2. For EACH obsolete review, use `reconcile_visual_review` with an appropriate getter.
   Read the result and account for the final state, including reversions and side effects.
3. Capture and inspect the replacement at readable scale with full coverage of ALL
   affected targets. Pass its visual assessment normally. An unknown numeric outcome
   still requires its own readback reconciliation.
4. Link the obsolete attempts to that passed replacement. Explain what was corrected,
   what the final readback confirms and how the inspected images cover the old scope.

The operation changes only the local review ledger. It preserves original numeric
receipts, evidence and assessments, records previous status and the replacement
assessment, and sets `status: superseded`, **not** `passed`; `task_complete` stays false
on the obsolete attempt. It cannot be reused as an early sample or assessed again.
Only pending/blocked/needs-correction attempts in the same native project, MCP client,
port and representation can be linked. Self-links, repeated IDs, already passed records,
missing readback, stale/tampered/unapproved replacement evidence are refused. Recapture
old MCP-client records explicitly before reconciliation when resuming after a restart.

The save gate resolves the obsolete obligation only while the referenced replacement
remains passed with the same assessment. Reopening that review blocks completion again.
No cyclic chains, automatic visual approvals, ignored modification stamps, model writes
or retries are introduced. The assistant must truthfully establish replacement coverage;
the server has no vision model and cannot infer semantic target coverage from JSON.


## Display refresh before capture

`redraw_current_database(port)` invokes the documented Tapir `RedrawCurrentDatabase`
command without parameters (introduced 1.8.0, schema verified at Tapir 2.0.0 bb71abf).
It redraws only the visible region of the current database, including background windows;
it does not edit elements or save. Older versions without the command report an error.
This is a view action, never a read-command gateway exception or a model write.

After navigation use: `fit_in_window` -> `redraw_current_database` -> bounded context
stabilization/capture -> actual image inspection -> assessment. Fit keeps its existing
contract and does not silently dispatch a newer-version command. Do not redraw between
capture and assessment: the redraw may advance the stamp and invalidate earlier evidence.
A successful redraw is not proof of current pixels or visual correctness. If the next
image remains stale/wrong/unreadable, keep the task incomplete and diagnose the display.
No redraw is hidden inside BitBlt or an evidence observation interval.
