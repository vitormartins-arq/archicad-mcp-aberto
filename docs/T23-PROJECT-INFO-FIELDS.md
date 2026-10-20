# T23: custom Project Info fields blocked by Tapir 1.7.0

The command exists, but it cannot provide the requested safe create/read-back workflow.
No MCP creation tool or simulated success is added in this delivery.

Source inspected: official Tapir tag `1.7.0`, commit
`02691b5d680b60c73317e8e49b78ab14dfd4c9d8`:

- [CreateProjectInfoFieldsCommand](https://github.com/ENZYME-APD/tapir-archicad-automation/blob/02691b5d680b60c73317e8e49b78ab14dfd4c9d8/archicad-addon/Sources/ProjectCommands.cpp#L411)
  accepts `projectInfoFields: [{projectInfoName, projectInfoValue?}]` and returns
  `fields`, containing field objects or errors.
- For `ServerMainVers_3000`, every item returns an explicit unsupported error:
  `TODO: this function was not migrated to AC30 yet. Failed to create project information field.`
- On earlier versions, the native command creates `autotext-<generated GUID>` IDs.
  `GetProjectInfoFieldsCommand::Execute` (same source, lines 105–147) only returns IDs
  beginning with PROJECT, KEYWORD, NOTES, SITE, BUILDING, CONTACT, CAD_TECHNICIAN or
  CLIENT, including their `autotext-<prefix>` forms. Arbitrary generated GUID IDs do not
  pass this filter. Therefore that read cannot check existing custom names or verify
  the new field's name and value, as T23 requires.
- A failure when setting an initial value happens after creation of the field. An
  error alone consequently does not establish that the command made no change.

This is source inspection, **not a live capture or live test**. It does not assert
that a particular installed add-on binary matches this tag.

Required upstream work: support creation on AC30 and expose a complete custom-field
inventory with IDs, names and values. After that is available in a supported Tapir
version, implement the 20-item limit, name-clash refusal, preview, one-use token,
explicit apply port, durable per-item receipts and independent read-back. Do not
work around the gap by changing IDs, claiming the create response is verification,
or teaching the fake to return fields that the inspected reader filters out.
