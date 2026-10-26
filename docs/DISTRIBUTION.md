# Material revisions and file names

`distribution.json` is the single source for the material's display names and revision.
The packaging script derives the filenames; do not type a second revision into CI,
rename a published binary to pretend it is newer, or infer a revision from a PR number.

| Material | Generated name for the proposed revision |
|---|---|
| Native add-on | `Archicad MCP - R03.apx` |
| MCP client bundle | `Servidor MCP - R03.mcpb` |
| Server source snapshot | `Servidor MCP - R03.zip` |
| Private companion source snapshot | `Complemento MCP - R03.zip` |

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

Keep each delivery under the existing `Archicad MCP` folder:

```text
Instalar/Archicad 30/Main/          integrated distribution
Instalar/Archicad 30/Em teste/      unaccepted experimental distribution
Servidor/Main/                    corresponding source snapshots
Servidor/Em teste/                experimental source snapshots
Documentação/Revisões.json         component commits, hashes and validation status
00 - Anteriores/                  previous distributions and document backups
```

Keep only the name and revision in each filename; the parent folder carries major
version and status. Update the Drive copies and delivery record whenever material is
delivered, preserve the previous revision, and keep test builds separate until accepted.
This workflow creates GitHub artifacts; it does not authenticate to Drive or silently
upload private material. The authorized delivery step copies the verified files there.
Never run a working clone, venv or installed APX from Drive/OneDrive.

Package naming is not runtime certification. It changes no add-on MDID, native command,
project element, installation or saved Archicad file. Keep the LAB Blocos importer separate.
