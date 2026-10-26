# LAB Windows installer

Double-click the generated EXE from Drive, allow the normal Windows administrator
prompt, then choose **Instalar / Atualizar**. Close Archicad yourself first; the
installer never closes or saves projects. The default is the installed major's
`Program Files/Graphisoft/Archicad <major>/Extensões/<LAB product>`; English builds
use `Add-Ons`. A custom Archicad root can be selected and its executable version
must match. Only Windows Archicad 29/30 is supported.

The EXE embeds the complete verified payload and needs no Python installation,
PowerShell execution-policy change, network download or manual working folder.
It is built with Microsoft's .NET Framework compiler already present on Windows.
Installers are currently unsigned; normal Windows publisher checks still apply.

## Replacing old versions

Identity is the registered native MDID resource, never filename similarity. Before
writing, the installer reads the current user's matching-major Add-On Manager
Include entries and searches the native extension directory, including subfolders.
An existing managed LAB folder must contain exactly one matching APX. Its entire
old payload (including obsolete runtime files) is moved aside; loose duplicate APXs
with the same MDID are also moved out of active loading. Other products are untouched.

The backup is under `Extensões/(LAB - Backups)/<product>/<unique transaction>`.
Graphisoft documents that subfolders beginning with `(` are skipped during loading.
The path and registry snapshots are stored in `restauracao.json`. The new complete
payload is SHA-256 verified before and after the move. Old registered paths are
replaced by one Include entry pointing at the new native location. External manually
stored files are retained for recovery but cease to be the registered active copy.
Only the selected major's current-user Include values for this MDID are changed.

Click **Restaurar versão anterior** in the same installer to restore the previous
native copies and Include entries. It retains the displaced new installation too.
Install failure rolls back moved native files and registry entries; if registry
rollback itself fails, native file recovery still runs and the error identifies
the backup. Never retry after an unknown result without examining that journal.
This is replacement with recovery, not irreversible deletion.

The installer refuses to write while any Archicad instance is running. It rejects
reparse points, conflicting destination contents, wrong executable major, corrupt
payloads and concurrent installers of the same MDID/major. A matching APX in a
custom designated Add-Ons directory is reported for manual resolution, rather
than silently deleting external user files. It does not touch Tapir, D5, native
extensions, MCP client configuration or Archicad projects.

## Build and provenance

```text
python tools/installer/build_installer.py --root . --input matching-build.apx --archicad 30 --payload-revision R05 --channel "em teste" --output packages
```

For the importer use `Tools/installer/build_installer.py` and the complete verified
update ZIP as input. The public name and material revision come from the existing
`distribution.json` or `config.json`. Do not overwrite an existing EXE. The JSON
receipt records source commit, installer hash, source-payload hash, per-file hashes,
MDID, channel and separate embedded payload revision. For companion APXs the caller
must supply a verified matching-DevKit build; a filename/MDID does not prove ABI.

An installer prepared from a prior integrated APX MUST retain its true payload
revision. A new packaging revision does not promote unmerged native features. Keep
unaccepted installers in `Em teste`; run a disposable-project acceptance test before
claiming real Archicad loading. Do not mix PR88 with a main server.

`InstallerTests.cs` exercises actual filesystem replacement, duplicate matching,
rollback, restoration and input rejection in a fresh temporary directory using an
APX supplied as a fixture. It never calls the GUI or edits the real registry.
Production Program Files/UAC, real Include registration and live loading remain
separate acceptance checks. Compiler/OS sources:

- https://github.com/ENZYME-APD/tapir-archicad-automation#installation
- https://archicadapi.graphisoft.com/documentation/structure-of-an-add-on

The three repositories intentionally carry identical installer sources. Update all
three together and compare hashes when changing the installation/recovery contract.
