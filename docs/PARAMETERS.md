# Element parameters: what can be read and changed

Scope: what an existing element's settings expose through the APIs this MCP uses,
and which tool reaches each. Sources read on 28/10/2026: Tapir tags 1.7.0 to 1.7.3
(`ElementGDLParameterCommands.cpp`, `ElementCommands.cpp`, `ExtendedElementCommands.cpp`,
`ElementCreationCommands.cpp`, `AddOnMain.cpp`) and the official Archicad 30 JSON API
command list (`archicad` Python package 30.3000). **No item below was tested on a real
Archicad yet, except the Object GDL write.** The live checklist is in `VALIDAR.md`.

## Four mechanisms, kept apart

| Mechanism | Read | Write | Notes |
|---|---|---|---|
| GDL parameters of the element's library part | `inspect_element_parameters`, `get_gdl_parameters` | `set_element_parameters` (target `gdl`), `set_gdl_parameters` (scalars) | Tapir only. The official JSON API has no GDL command. |
| Door/window marker (the stamp) | `inspect_element_parameters` | `set_element_parameters` (target `marker`) | Tapir 1.7.1+. Scalars only (Tapir refuses marker arrays). |
| Native element fields | `get_element_details`, `inspect_element_parameters` | the `modify_*` tool named in `writable_by` | Tapir `GetDetailsOfElements` and `Modify*`. |
| Layer, classification, properties, placement, lock, favorite | their tools | `set_element_layers`, `set_classifications`, `set_property_values`, `move_elements`, `rotate_elements`, `lock_elements`, `apply_favorites` | Properties and classifications also through the official API. |

Tool settings (the defaults of a tool, not a placed element) are favorites:
`list_favorites`, `apply_favorites`, `create_favorites_from_elements`,
`update_favorites_from_elements`.

## Coverage by element type

`get_element_capabilities(element_types=[...])` returns this table as data, and with
element GUIDs adds the hotlink/lock state and the installed Tapir version.

| Type | GDL read/write | Marker | Native write tool (MCP) | Native fields Tapir 1.7.3 has, not exposed yet | Not reachable |
|---|---|---|---|---|---|
| Object | yes / yes (live-tested write) | no | `modify_objects` (origin, level, dimensions) | | |
| Lamp | yes / yes | no | `modify_lamps` (+ lightIsOn) | | |
| Door, Window | yes / yes | yes (1.7.1) | `modify_doors`, `modify_windows` (width, height, sillHeight, centerOffset) | reflected, refSide, oSide, reveal, revealDepthOffset | |
| Skylight | yes / yes | no | none | | no native Modify command |
| Zone | yes (stamp) / yes | no | `update_zones` (recalculate only) | stampPosition, stampAngle, referencePosition | name/number are properties |
| Label | symbol labels: yes / yes | no | `modify_labels` (text, height) | runs, style, symbolStyle, leaderLine | text labels have no GDL |
| Drawing | title: yes / yes | no | none | clip polygon, scale, angle, title, border… | |
| Curtain wall frame/panel/junction/accessory | yes / yes | no | none | | curtain wall itself: no Modify |
| Wall | no | no | `modify_walls` (height, thickness, bottomOffset, begin/end) | structure, composite, profile, slant, top link, materials, visibility… | |
| Slab | no | no | `modify_slabs` (thickness, level) | structure, composite, outline, holes, materials | |
| Column | no | no | `modify_columns` | rotation, slant, top link, profile… | |
| Beam | no | no | `modify_beams` | offset, slant, profile, holes… | |
| Roof | no | no | `modify_roofs` (thickness, level, overhang, levels) | structure, composite, outline, holes | |
| Mesh | no | no | `modify_meshes` | pens, polygon, holes | |
| Morph | no | no | `modify_morphs` | many display fields | |
| Text | no | no | `modify_texts` | runs, full style | |
| Line, arc, circle, hotspot, spline, polyline, fill | no | no | none | geometry and pens through `SetDetailsOfElements` | |
| Opening (Opening tool) | no | no | none | `SetOpeningDetails`, `SetOpeningFloorPlanParameters` (AC29+) | |
| Stair | no | no | none | | no Modify; risers/treads/structures have no GDL entry point |
| Railing and its parts | no | no | none | | no Modify and no GDL entry point |
| Dimension | no | no | none | | read only (`get_dimension_data`) |

Why the GDL list is closed: Tapir's `GetGDLParametersOfElements` looks the library part
index up only for the types above. For any other type it passes index -1 to the native
API, so the MCP never sends those types (a stair or railing part could otherwise reach an
uninitialised parameter list). Opening it up is a candidate for our own add-on.

## Inspection shape

Each parameter keeps the library part's own data, in its own order:

```json
{"name": "<internal name>", "description": "<dialog text>", "index": 11,
 "type": "Integer", "unit": null, "value": 1, "value_description": "<text of the value>",
 "options": [{"value": 1, "description": "..."}], "limits": {"lower": [...], "upper": [...],
 "steps": [...]}, "custom_value_allowed": false, "dimensions": [2, 1],
 "item_descriptions": [...], "flags": ["Child"], "is_locked": false,
 "editable": true, "edit_blocked_reason": null, "group": "<Title above>", "parent": "<row above>"}
```

`group` and `parent` come only from the order of the list (Title rows, Child flag). They
are how a door's leaf, frame, handle, opening and 2D/3D pages can be told apart without
guessing names. `name_contains` filters by name, description, value description and group.

Units: Length in metres, Angle in radians, colour components 0..1; pens, line types,
fills, surfaces, building materials and profiles are attribute indices.

## Change flow (`set_element_parameters`)

1. Read the current state (`inspect_element_parameters`).
2. Dry run: each change is checked against type, flags (Fixed, Hidden, HiddenFromScript,
   Disabled), the script lock, the reported options/limits and the array shape. All
   problems are listed together, per field. Values already set are marked `unchanged`
   and not sent. The plan binds the project, the element set, every current parameter
   value, the placement, layer, classification and user-defined property values.
3. Apply with the explicit port and the single-use token. Any change since the dry run
   refuses the token. All GDL changes go in one undoable `SetGDLParametersOfElements`;
   marker changes in a second command; `run_parameter_script=true` adds a third.
   `undo_steps` says how many Ctrl+Z revert the batch.
4. Read back after the parameter script. A value Archicad holds differently is
   `not_applied`, never success. Other parameters the script changed are listed in
   `dependent_changes`. GUID, host wall, placement (`centerOffset`, `sillHeight`,
   origin, angle…), library part, layer and classification are compared; any change
   fails the element. User-defined property values that changed are listed in
   `unrequested_property_changes` (expressions can change legitimately).
5. An unknown outcome (timeout, lost response) stays `unknown`. The later steps are not
   sent, the read-back is attached as observation, and the token is consumed: inspect
   before preparing a new request.

Saving follows the standing rule: `begin_model_task` before the first change (verified
backup PLN in `00 - Anteriores`), `finish_model_task` at the end (same PLN).

## Version notes (Tapir source)

| Behaviour | Since |
|---|---|
| GDL read/write for doors, windows, skylights, zones, labels, drawings, curtain wall parts | 1.7.0 or earlier (owner type taken from the element; older tags not checked) |
| Arrays written item by item through `ChangeAParameter` (script runs per item) | 1.7.2 (#557); refused before |
| Angle values written in radians | 1.7.3 (#1401); before, the MCP converts to degrees |
| Marker parameters | 1.7.1 |
| `RunParameterScriptOfElements` | 1.7.3 |
| Locked layer / locked element reported as such on a failed write | 1.7.3 |

Known API limits: Tapir reports only the lower bound of a closed range (`possibleValues`),
so the read-back is the final check; arrays cannot be resized; Dictionary parameters
cannot be written; a closed value list is enforced in the dry run only when Tapir says
`canHaveCustomValue: false`.

## Example: a door's handle

```text
inspect_element_parameters(element_guids=[door], port=19723, name_contains="handle")
set_element_parameters(changes=[{"element_guid": door, "name": "<name from inspection>",
                                 "value": "<one of its options>"}], port=19723)
set_element_parameters(..., dry_run=false, confirmation_token="<token>")
```

The receipt must show the change `verified`, `identity_after.details.ownerElementId`
equal to the same wall and no `identity_changed`.
