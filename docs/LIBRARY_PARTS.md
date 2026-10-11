# Loaded library parts: API investigation

Scope: Tapir 1.7.0 source at `02691b5d680b60c73317e8e49b78ab14dfd4c9d8`,
plus the published official JSON API/Python wrapper command lists for Archicad 29/30.
Read-only source research; no live Archicad calls were made by Codex.

| Confirmed command | What it returns | Primary source |
|---|---|---|
| Tapir `GetAvailableLibraryParts` | Available parts: `guid`, `index`, `documentName`, `fileName`, `typeId`; `skippedCount` and optional `skippedSample` identify a partial inventory. Optional `filterByTypeId`. | [Schema and enumeration](https://github.com/ENZYME-APD/tapir-archicad-automation/blob/02691b5d680b60c73317e8e49b78ab14dfd4c9d8/archicad-addon/Sources/LibraryCommands.cpp#L579), [registration since 1.5.0](https://github.com/ENZYME-APD/tapir-archicad-automation/blob/02691b5d680b60c73317e8e49b78ab14dfd4c9d8/archicad-addon/Sources/AddOnMain.cpp#L924) |
| Tapir `GetLibraries` | Loaded library containers, including name/path/type/availability; not individual parts. | [Schema](https://github.com/ENZYME-APD/tapir-archicad-automation/blob/02691b5d680b60c73317e8e49b78ab14dfd4c9d8/archicad-addon/Sources/LibraryCommands.cpp#L265), [implementation](https://github.com/ENZYME-APD/tapir-archicad-automation/blob/02691b5d680b60c73317e8e49b78ab14dfd4c9d8/archicad-addon/Sources/LibraryCommands.cpp#L482), [registration since 1.0.1](https://github.com/ENZYME-APD/tapir-archicad-automation/blob/02691b5d680b60c73317e8e49b78ab14dfd4c9d8/archicad-addon/Sources/AddOnMain.cpp#L900) |
| Tapir `GetDetailsOfElements` | For placed library-based elements, `details.libPart` contains name, `ownUnID` and `parentUnID`. This does not enumerate unplaced parts. | [AddLibPartBasedElementDetails](https://github.com/ENZYME-APD/tapir-archicad-automation/blob/02691b5d680b60c73317e8e49b78ab14dfd4c9d8/archicad-addon/Sources/ElementCommands.cpp#L710) |
| Official `API.ExecuteAddOnCommand` | Invokes a registered add-on command; use namespace `TapirCommand` for the commands above. | [Official wrapper reference](https://archicadapi.graphisoft.com/archicadPythonPackage/archicad.html#archicad.Commands.ExecuteAddOnCommand) |

No separate official JSON command listing individual loaded library parts was found in
[published Archicad 29/30 wrapper command lists](https://archicadapi.graphisoft.com/archicadPythonPackage/archicad.html).
The C++ functions `ACAPI_LibraryPart_GetNum` and `ACAPI_LibraryPart_Get` used by Tapir are
native API functions, not JSON command names. There is no need to invent a JSON name or
build another add-on: use the confirmed Tapir inventory command.

`list_library_parts(port, name_contains, offset, limit)` reads this inventory and pages
up to 500 rows, with GUID/index/name/type and native document/file names preserved.
Name substring matching is case-insensitive. `total` counts the readable filtered rows;
`partial=true` means some available parts could not be read, so it is not a complete census.

`create_objects` validates each requested document name against Object entries in the
inventory during dry run and again before applying. Names are matched case-insensitively;
unknown names refuse the whole preview only when the inventory is complete. Names with
distinct matching Object GUIDs remain ambiguous and refuse the preview. When
`skippedCount > 0`, a missing name marks only that item as `status="unconfirmed"` with
a warning; other items remain ready. No GUID is asserted for an unconfirmed item.
Apply sends it to `CreateObjects`, which resolves the name and reports success or a
native error per item, without aborting the other objects. Successful creations still
undergo the usual geometry/name verification.
For confirmed names, the selected part GUID is bound into confirmation identity. Native per-item errors remain
possible after preflight (defaults, permissions or a change during dispatch) and retain
per-item receipts. No files or projects are saved, deleted or unlocked by the listing.

Fixture: `tests/fixtures/tapir170_library_parts_documented.json` is source-derived with
synthetic values, explicitly **not** a live capture. Test only through MockTransport.
