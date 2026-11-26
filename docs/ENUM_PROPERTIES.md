# Editable single-enum property values

`set_property_values` now supports editable `singleEnum` properties through the
official Graphisoft JSON API. Pass an exact nonlocalized identifier listed by the
property definition, such as `New`, or an exact GUID enum identifier. Display labels,
ambiguous/unknown choices, unreadable choices and definitions not explicitly editable
are refused. The complete definition and current value participate in preview/token
verification. Apply resolves the ID from that definition, sends a normal single-enum
value to `API.SetPropertyValuesOfElements`, and verifies the stored identifier.
Existing scalar behavior and single-use receipts remain unchanged. No PLN is saved.

For renovation, change the element property rather than the view's renovation filter.
In the tested AC30 BRA session the built-in property GUID was
`9CF14061-6E9C-45BE-BD8F-D3BCF59D218E`, with `New` displayed as `A Construir`.
Confirm the definition/choices in the target project; use explicit element GUIDs,
port and the project's authorized verified-backup/task workflow.

## Real validation, 2026-11-26

Genuine MCP ClientSession over stdio, AC30 build 3001 BRA, Tapir 1.7.3, disposable
`Sem Nome` only, port 19725. Each operation used its own preview/token and the normal
server dispatch, not a raw JSON write or a guard bypass:

- Slab: `Existing` → `New`; write and official read-back verified.
  Receipt `6666df3a-8224-4bcd-b6d8-d5ebd23d88c9`.
- Object `Ar Condicionado Cassete Teto`: `Existing` → `New`; write and official
  read-back verified. Receipt `0e6416c2-915f-488c-aec6-b7da876a351d`.

No installed APX was changed; no client PLN was edited/saved; no layer visibility or
renovation filter was changed. Reload the Python MCP session to use the correction.
This validates the enum edit, not the separate favorite-creation, label-position or
radial-dimension investigations. Undo and save/reopen were not tested for this change.
