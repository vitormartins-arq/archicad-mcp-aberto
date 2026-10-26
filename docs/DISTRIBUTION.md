# Material revisions and file names

`distribution.json` is the single source for the material's display names and revision.
The packaging script derives the filenames; do not type a second revision into CI,
rename a published binary to pretend it is newer, or infer a revision from a PR number.

| Material | Generated name for the proposed revision |
|---|---|
| Native add-on | `LAB - Complemento MCP - R04.apx` |
| MCP client bundle | `LAB - Servidor MCP - R04.mcpb` |
| Server source snapshot | `LAB - Servidor MCP - R04.zip` |
| Private companion source snapshot | `LAB - Complemento MCP Fonte - R04.zip` |

R01 and R02 already identify the historical Drive distribution and the experimental
PR #88 distribution. R03 is reserved by this proposed packaging change; it does not
rename, replace or promote those existing files. Material revisions are independent
of Python package versions and version tags. Do not change the package or MCP bundle
manifest version just to change a filename.

## When material changes

Advance `revision` before publishing changed material. This includes changed source
snapshots, documentation shipped in those snapshots, packaging, or binary content.
The PR check compares with its base: any tracked change requires a larger revision,
except the first adoption of this policy. Revisions belong to each repository's material;
matching labels across repositories alone do not prove compatibility. Keep the exact
component commits and validation status in the delivery record.

The packager refuses an existing filename with different bytes and a receipt from a
different source commit. It preserves the input binary and writes a `Revisoes - R03.json`
receipt with its SHA-256, source commit and Archicad major. Never replace a previous
release merely because it used an older naming convention.

## Package commands

```sh
python tools/distribution.py name addon
python tools/distribution.py check --base origin/main
python tools/distribution.py stage addon --input path/to/build.apx --archicad 30 --output packages
python tools/distribution.py source server_source --archicad 30 --output packages
```

Use `source addon_source` in the private companion repository. Source snapshots contain
the full tracked checkout at HEAD, not the working tree, credentials, venv or `.git`.
Build APXs with the matching DevKit; `--archicad` labels an already compatible build
and does not convert or validate its ABI. Internal CMake target names and CI job/artifact
identifiers may retain the technical major/platform suffix; user-facing files follow
the table. Wheel/sdist filenames retain the Python packaging standard so installers work.

## Drive delivery

Keep one folder per repository under `Archicad/Add-Ons Archicad`:

```text
LAB - Servidor MCP/   Python MCP server, not an Archicad APX
LAB - MCP Escritório/      private Python MCP layer, not another APX
LAB - Importador de Blocos e Texturas/           native importer, complete package with engine/runtime
LAB - Complemento MCP/   native MCP companion
```

Within each repository folder, `Atual` is the current integrated distribution or
explicitly labelled latest candidate, `Em teste` contains unaccepted PR material, and
`00 - Anteriores` keeps previous material. Put Archicad 29/30 in separate child folders.
Keep source snapshots and the delivery receipt alongside the matching material.
The companion APXs built in the open server and private add-on repository share an
MDID: they are alternatives, not independent plug-ins to load together.


Keep only the name and revision in each filename; the parent folder carries major
version and status. Use the exact repository folder above; update the Drive copies and delivery record whenever material is
delivered, preserve the previous revision, and keep test builds separate until accepted.
This workflow creates GitHub artifacts; it does not authenticate to Drive or silently
upload private material. The authorized delivery step copies the verified files there.
Never run a working clone, venv or installed APX from Drive/OneDrive.

Package naming is not runtime certification. It changes no add-on MDID, native command,
project element, installation or saved Archicad file. Keep the LAB Blocos importer separate.

## LAB prefix (26 October 2026)

All user-facing names start with `LAB - `. R04 supersedes proposed R03; existing
R01/R02/R03 binaries keep their revisions when given a LAB delivery label. The native
Add-On Manager label is changed in source and requires a new build to take effect.
MDID, command namespaces and technical project identifiers remain unchanged.
