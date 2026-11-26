# Native angular dimensions and documentation fixes

Development candidate; requires the matching private companion R33.

`get_angle_dimensions` reads type, radians, arc geometry, four references and favorite
style, optionally restricted to1..100 GUIDs. `create_angle_dimensions` accepts1..20
items with favorite, floor_index, position and exactly four references containing
element_guid/in_index/neig_id (from get_element_hotspots). Pair0–1 and pair2–3 define
the directions. Native planning resolves the current coordinates and rejects missing
or ambiguous references rather than creating a static dimension.

Creation uses the shared resolve_port, snapshot, single-use token and receipt flow,
one native Undo transaction and independent association/value/style read-back.
The native plan is compared again inside the companion before any creation. Unknown
outcomes remain unverified and are not retried automatically. Lengths use metres;
angles use radians. Caller coordinates do not substitute for native references.

Current limits: floor plans, local references on one story, visible unlocked favorite
layer, measured-angle favorites without fixed note or leader. Exact-order duplicates
at the same position are reused. Equivalent reversed references are not normalized.
Live rebuild/association/Undo/appearance acceptance is still required.

Label creation now reads the native favorite class and explicitly preserves Symbol
instead of forcing Text. Symbol content stays in the favorite; text and height_mm
are not used to overwrite its GDL representation. Saved navigator views use native
GoToView to restore stored representation, not just the database. Both paths require
the updated companion and deliberately fail when it cannot provide the contract.

Offline protocol tests and AC29/30 native builds are separate from real acceptance.
No active MCP runtime, installed APX or WG Formosa model was changed.
