"""One layer over every mechanism that reads or changes an existing element's settings.

Four mechanisms, each with its own API and checks:

- GDL parameters of library part based elements (Tapir Get/SetGDLParametersOfElements);
- the marker (stamp) of doors and windows (Tapir Get/SetMarkerParametersOfElements);
- native element fields (Tapir GetDetailsOfElements to read, the modify_* tools to write);
- layer, classification, properties, placement and favorites (their own tools).

``get_element_capabilities`` says which applies to an element and through which tool;
``inspect_element_parameters`` reads them; ``set_element_parameters`` changes GDL and
marker parameters with a preview, one token, read-back after the parameter script and an
identity check (GUID, host wall, placement, layer, classification). Native fields keep
their tools, so the field logic lives in one place. Metres and radians. Never saves.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError, resolve_port
from archicad_mcp_aberto.tools import classifications, edit, gdl, meshes, modify, read, write

MAX_ELEMENTS = 20
MAX_CHANGES = 100
MAX_PROPERTIES = 200  # user-defined properties compared before/after a write

# Native fields Tapir 1.7.3 can write that no MCP tool exposes yet (source: Modify*/
# SetDetailsOfElements schemas at tag 1.7.3). Listed so a gap is never hidden.
TAPIR_ONLY = {
    "Wall": [
        "geometryType", "arcAngle", "structureType", "buildingMaterialId", "compositeId",
        "profileId", "referenceLineLocation", "profileType", "slantAlpha", "slantBeta",
        "topOffset", "relativeTopStory", "zoneRel", "visibility", "referenceMaterial",
        "oppositeMaterial", "sideMaterial", "contourPen", "displayOption", "offset",
    ],
    "Slab": [
        "structureType", "buildingMaterialId", "compositeId", "referencePlaneLocation",
        "polygonOutline", "holes", "topMaterial", "sideMaterial", "bottomMaterial", "floorFill",
    ],
    "Column": [
        "axisRotationAngle", "coreAnchor", "isSlanted", "slantAngle", "topOffset",
        "relativeTopStory", "circleBased", "buildingMaterialId", "profileId", "coverFill",
    ],
    "Beam": [
        "offset", "slantAngle", "arcAngle", "isSlanted", "profileAngle", "anchorPoint",
        "buildingMaterialId", "profileId", "holes", "coverFill",
    ],
    "Window": ["reflected", "refSide", "oSide", "reveal", "revealDepthOffset"],
    "Door": ["reflected", "refSide", "oSide", "reveal", "revealDepthOffset"],
    "Roof": ["structureType", "buildingMaterialId", "compositeId", "polygonOutline", "holes"],
    "Mesh": ["floorIndex", "contourPen", "levelPen", "lineTypeIndex", "polygonCoordinates"],
    "Morph": ["rotationDegreesZ", "showContour", "showFill", "cutFillPen", "coverFillType"],
    "Text": ["runs", "style (font, pen, frame, anchor...)", "floorIndex"],
    "Label": ["runs", "style", "symbolStyle", "leaderLine"],
    "Zone": ["stampPosition", "stampAngle", "fixedStampAngle", "referencePosition"],
    "Line": ["begCoordinate", "endCoordinate", "linePen", "lineType", "roomSeparator"],
    "Arc": ["origin", "radius", "angle", "ratio", "begAngle", "endAngle", "reflected"],
    "Circle": ["origin", "radius", "angle", "ratio"],
    "Hotspot": ["position", "height", "penIndex"],
    "Spline": ["linePen", "lineType", "roomSeparator"],
    "PolyLine": ["coordinates", "arcs"],
    "Hatch": ["coordinates", "arcs"],
    "Drawing": [
        "clipPolygon", "isCutWithFrame", "drawingScale", "ratio", "angle", "pos", "nameType",
        "numberingType", "hasBorderLine", "borderPenIndex", "titleLibraryPartIndex",
    ],
    "Opening": ["SetOpeningDetails (geometry, extrusion)", "SetOpeningFloorPlanParameters"],
}  # fmt: skip

# Native write tools by element type: (MCP tool, input model).
WRITE_TOOLS = {
    "Wall": ("modify_walls", edit.WallModify),
    "Slab": ("modify_slabs", modify.SlabModify),
    "Column": ("modify_columns", modify.ColumnModify),
    "Beam": ("modify_beams", modify.BeamModify),
    "Window": ("modify_windows", modify.OpeningModify),
    "Door": ("modify_doors", modify.OpeningModify),
    "Object": ("modify_objects", modify.ObjectModify),
    "Lamp": ("modify_lamps", modify.LampModify),
    "Roof": ("modify_roofs", modify.RoofModify),
    "Text": ("modify_texts", modify.TextModify),
    "Label": ("modify_labels", modify.LabelModify),
    "Morph": ("modify_morphs", modify.MorphModify),
    "Mesh": ("modify_meshes", meshes.MeshModify),
}

# What the API cannot reach today, by type (Tapir 1.7.3 and the official AC30 JSON API).
NOT_ACCESSIBLE = {
    "Stair": "No Modify command: stair geometry/rules are read only (get_element_details). "
    "Risers, treads and structures are subelements without a GDL entry point in Tapir.",
    "Railing": "No Modify command and no GDL entry point for posts, rails, balusters or "
    "panels in Tapir 1.7.3; read through get_subelements/get_element_details only.",
    "CurtainWall": "No Modify command for the curtain wall itself; frames, panels, "
    "junctions and accessories have GDL parameters.",
    "Skylight": "No native Modify command; size and settings through its GDL parameters.",
    "Opening": "Tapir 1.7.3 SetOpeningDetails/SetOpeningFloorPlanParameters (Archicad 29+) "
    "exist but are not exposed by this MCP yet.",
    "Dimension": "Read with get_dimension_data; no edit command.",
    "Zone": "Name/number are properties; the stamp is GDL. update_zones recalculates "
    "geometry; stamp position fields are Tapir-only.",
}

# Fields of GetDetailsOfElements that identify an element and its placement. A parameter
# write that changes one of them is never reported as verified.
IDENTITY_KEYS = (
    "ownerElementId",
    "ownerElementType",
    "origin",
    "angle",
    "level",
    "zCoordinate",
    "centerOffset",
    "sillHeight",
    "reflected",
    "refSide",
    "oSide",
    "begCoordinate",
    "endCoordinate",
    "position",
    "libPart",
)

COMMON = [
    {"what": "layer", "read": "get_element_details", "write": "set_element_layers"},
    {"what": "classification", "read": "set_classifications (dry run)",
     "write": "set_classifications"},
    {"what": "properties", "read": "get_properties", "write": "set_property_values"},
    {"what": "position", "write": "move_elements"},
    {"what": "rotation", "write": "rotate_elements"},
    {"what": "lock", "write": "lock_elements / unlock_elements"},
    {"what": "favorite settings", "write": "apply_favorites"},
]  # fmt: skip


def _fields(model) -> list[str]:
    return [name for name in model.model_fields if name != "guid"]


def type_capabilities(kind: str, tapir: tuple[int, ...] | None = None) -> dict:
    """Mechanisms for one element type. ``tapir`` None means: not checked against a version."""

    def needs(since):
        if tapir is None:
            return {"requires_tapir": ".".join(map(str, since))}
        return {} if tapir >= since else {"blocked": f"needs Tapir {'.'.join(map(str, since))}"}

    owner = kind in gdl.GDL_OWNER_TYPES
    out: dict[str, Any] = {
        "type": kind,
        "gdl": {
            "read": owner,
            "write": owner,
            "via": "inspect_element_parameters / set_element_parameters" if owner else None,
            "live_validated_write": kind in gdl.LIVE_WRITE_TYPES,
            **(
                {"arrays": needs(gdl.ARRAY_WRITE_SINCE) or True, "notes": _gdl_notes(kind)}
                if owner
                else {"reason": "Not a library part based element in Tapir 1.7.3."}
            ),
        },
    }
    if kind in gdl.MARKER_TYPES:
        out["marker"] = {"read": True, "write": True, "scalars_only": True,
                         **needs(gdl.MARKER_SINCE)}  # fmt: skip
    tool = WRITE_TOOLS.get(kind)
    out["native"] = {
        "read": "get_element_details (Tapir GetDetailsOfElements)",
        "write": [{"tool": tool[0], "fields": _fields(tool[1])}] if tool else [],
        "tapir_only_fields": TAPIR_ONLY.get(kind, []),
    }
    if kind in NOT_ACCESSIBLE:
        out["native"]["limitation"] = NOT_ACCESSIBLE[kind]
    out["parameter_script"] = needs(gdl.SCRIPT_SINCE) or True if owner else False
    out["common"] = COMMON
    return out


def _gdl_notes(kind: str) -> str:
    if kind in gdl.SIZE_LINKED_TYPES:
        return "A/B also resize the element (Tapir copies them to its own size)."
    return "Parameters are written to the element memo; size fields are not linked."


async def _rows(client, port, command, key, guids, timeout=None) -> dict[str, Any]:
    if not guids:
        return {}
    extra = {} if timeout is None else {"timeout": timeout}
    result = await client.tapir(port, command, {"elements": read.element_ids(guids)}, **extra)
    rows = result.get(key)
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError(f"Unexpected {command} response cardinality.")
    return dict(zip(guids, rows, strict=True))


async def _elements(client, guids, port):
    """Port, Tapir version and the details/editability of the given elements."""
    if not 1 <= len(guids) <= MAX_ELEMENTS:
        raise ValueError(f"Pass between 1 and {MAX_ELEMENTS} elements.")
    if len(set(guids)) != len(guids):
        raise ValueError("Duplicate element GUIDs are not allowed.")
    port = await resolve_port(client, port)
    version = gdl.version((await client.tapir(port, "GetAddOnVersion")).get("version"))
    elements = read.element_ids(guids)
    result = await client.tapir(
        port, "GetDetailsOfElements", {"elements": elements, "fields": write.DETAIL_FIELDS}
    )
    rows = result.get("detailsOfElements")
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected element details response.")
    editable = await client.tapir(
        port, "FilterElements", {"elements": elements, "filters": ["IsEditable"]}
    )
    free = {e["elementId"]["guid"].upper() for e in editable.get("elements", [])}
    return port, version, dict(zip(guids, rows, strict=True)), free


def _state(guid, row, free) -> dict:
    if not isinstance(row, dict) or "error" in row or row.get("type") in (None, "Unknown"):
        return {"guid": guid, "error": row.get("error") if isinstance(row, dict) else row}
    blocked = []
    if row.get("hotlinkId"):
        blocked.append("element belongs to a hotlink; edit the source file")
    if guid not in free:
        blocked.append("element is locked, on a locked layer or not reserved")
    return {
        "guid": guid,
        "type": row["type"],
        "floorIndex": row.get("floorIndex"),
        "layerIndex": row.get("layerIndex"),
        "hotlinkId": row.get("hotlinkId"),
        "editable": not blocked,
        "edit_blocked_reasons": blocked,
    }


async def get_element_capabilities(
    client: ArchicadClient,
    element_guids: list[str] | None = None,
    element_types: list[str] | None = None,
    port: int | None = None,
) -> dict:
    """Which settings of each element can be read or changed, and by which tool/command.

    With element GUIDs, also the element's hotlink/lock state and the installed Tapir
    version. With element_types only, the static matrix (no Archicad call).
    """
    if not element_guids and not element_types:
        raise ValueError("Pass element_guids or element_types.")
    out: dict[str, Any] = {"note": "Source-derived from Tapir 1.7.3 and the official "
                           "Archicad 30 JSON API; see docs/PARAMETERS.md."}  # fmt: skip
    if element_types:
        out["types"] = [type_capabilities(t) for t in dict.fromkeys(element_types)]
    if element_guids:
        guids = [e["elementId"]["guid"] for e in read.element_ids(element_guids)]
        port, version, rows, free = await _elements(client, guids, port)
        out.update(port=port, tapir_version=".".join(map(str, version)))
        out["elements"] = []
        for guid in guids:
            state = _state(guid, rows[guid], free)
            if "type" in state:
                state["capabilities"] = type_capabilities(state["type"], version)
            out["elements"].append(state)
    return out


def _matches(row: dict, needle: str | None) -> bool:
    if not needle:
        return True
    text = " ".join(
        str(row.get(k) or "") for k in ("name", "description", "value_description", "group")
    )
    return needle.casefold() in text.casefold()


async def inspect_element_parameters(
    client: ArchicadClient,
    element_guids: list[str],
    port: int | None = None,
    name_contains: str | None = None,
    include_native: bool = True,
    include_marker: bool = True,
) -> dict:
    """Read every reachable setting of up to 20 elements, without changing anything.

    GDL and marker parameters come with internal name, description, type, unit, value,
    value description, options, limits, array shape, flags, group and edit state. Native
    fields come from GetDetailsOfElements with the tool that can change each. Parameter
    names and options are exactly what the library part reports; none are inferred.
    """
    guids = [e["elementId"]["guid"] for e in read.element_ids(element_guids)]
    port, version, rows, free = await _elements(client, guids, port)
    owners = [g for g in guids if rows[g].get("type") in gdl.GDL_OWNER_TYPES]
    openings = [g for g in guids if rows[g].get("type") in gdl.MARKER_TYPES]
    gdl_rows = await _rows(
        client, port, "GetGDLParametersOfElements", "gdlParametersOfElements", owners
    )
    marker_rows = {}
    if include_marker and openings and version >= gdl.MARKER_SINCE:
        marker_rows = await _rows(
            client, port, "GetMarkerParametersOfElements", "markerParametersOfElements", openings
        )
    out = []
    for guid in guids:
        state = _state(guid, rows[guid], free)
        if "type" not in state:
            out.append(state)
            continue
        kind = state["type"]
        details = rows[guid].get("details") if isinstance(rows[guid].get("details"), dict) else {}
        state["identity"] = {k: details[k] for k in IDENTITY_KEYS if k in details}
        if guid in gdl_rows:
            raw = gdl_rows[guid]
            if isinstance(raw, dict) and isinstance(raw.get("parameters"), list):
                described = gdl.describe(raw["parameters"])
                state["gdl"] = {
                    "count": len(described),
                    "parameters": [p for p in described if _matches(p, name_contains)],
                }
            else:
                state["gdl"] = {"error": raw.get("error") if isinstance(raw, dict) else raw}
        else:
            state["gdl"] = {"available": False, "reason": "No GDL parameters in Tapir."}
        if kind in gdl.MARKER_TYPES and include_marker:
            if version < gdl.MARKER_SINCE:
                state["marker"] = {"available": False, "reason": "needs Tapir 1.7.1"}
            else:
                raw = marker_rows.get(guid, {})
                if isinstance(raw, dict) and isinstance(raw.get("parameters"), list):
                    described = gdl.describe(raw["parameters"])
                    state["marker"] = {
                        "library_part": raw.get("libPart"),
                        "count": len(described),
                        "parameters": [p for p in described if _matches(p, name_contains)],
                    }
                else:
                    state["marker"] = {"error": raw.get("error") if isinstance(raw, dict) else raw}
        if include_native:
            tool = WRITE_TOOLS.get(kind)
            exposed = set(_fields(tool[1])) if tool else set()
            state["native"] = {
                "fields": details,
                "writable_by": {f: tool[0] for f in exposed} if tool else {},
                "tapir_only_fields": TAPIR_ONLY.get(kind, []),
                **({"limitation": NOT_ACCESSIBLE[kind]} if kind in NOT_ACCESSIBLE else {}),
            }
        out.append(state)
    return {
        "port": port,
        "tapir_version": ".".join(map(str, version)),
        "name_contains": name_contains,
        "elements": out,
        "note": "Lengths in metres, angles in radians. Change GDL/marker parameters with "
        "set_element_parameters and native fields with the tool in writable_by.",
    }


Scalar = str | bool | int | float


class ParameterChange(write.InputModel):
    element_guid: str
    name: Annotated[str, Field(min_length=1, max_length=255)]
    value: Scalar | list[Scalar] | list[list[Scalar]]
    target: Literal["gdl", "marker"] = "gdl"

    @field_validator("element_guid")
    @classmethod
    def canonical_guid(cls, value):
        return str(UUID(value)).upper()

    @field_validator("name")
    @classmethod
    def unpadded(cls, value):
        if value != value.strip():
            raise ValueError("Parameter name must be unpadded.")
        return value


class ParameterRequest(write.InputModel):
    changes: Annotated[list[ParameterChange], Field(min_length=1, max_length=MAX_CHANGES)]
    run_parameter_script: bool = False


async def _identity(client, port, guids, timeout=None) -> dict[str, dict]:
    """Placement, host, layer, classification and user-defined property values."""
    extra = {} if timeout is None else {"timeout": timeout}
    result = await client.tapir(
        port,
        "GetDetailsOfElements",
        {"elements": read.element_ids(guids), "fields": write.DETAIL_FIELDS},
        **extra,
    )
    rows = result.get("detailsOfElements")
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected element details response.")
    out = {}
    for guid, row in zip(guids, rows, strict=True):
        if not isinstance(row, dict) or "error" in row:
            out[guid] = {"error": row.get("error") if isinstance(row, dict) else row}
            continue
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        out[guid] = {
            "type": row.get("type"),
            "floorIndex": row.get("floorIndex"),
            "layerIndex": row.get("layerIndex"),
            "hotlinkId": row.get("hotlinkId"),
            "details": {k: details[k] for k in IDENTITY_KEYS if k in details},
            "classifications": {},
            "properties": {},
        }
    systems = (await client.command(port, "GetAllClassificationSystems", **extra)).get(
        "classificationSystems", []
    )
    system_ids = [s["classificationSystemId"]["guid"] for s in systems if isinstance(s, dict)]
    live = [g for g in guids if "error" not in out[g]]
    if system_ids and live:
        current = await classifications._current(
            client, port, [(g, s) for g in live for s in system_ids], timeout
        )
        for (guid, system), value in current.items():
            out[guid]["classifications"][system] = value
    ids = (await client.command(port, "GetAllPropertyIds", {"propertyType": "UserDefined"},
                                **extra)).get("propertyIds", [])  # fmt: skip
    props = [p["propertyId"]["guid"] for p in ids if isinstance(p, dict)][:MAX_PROPERTIES]
    if props and live:
        values = await write._read_values(client, port, [(g, p) for g in live for p in props],
                                          timeout)  # fmt: skip
        for (guid, prop), value in values.items():
            out[guid]["properties"][prop] = value
    return out


def _identity_mismatches(before: dict, after: dict) -> tuple[list[str], list[str]]:
    """(identity fields that changed, user-defined properties whose value changed)."""
    if "error" in after:
        return ["element"], []
    changed = [
        key
        for key in ("type", "floorIndex", "layerIndex", "hotlinkId")
        if before.get(key) != after.get(key)
    ]
    for key, value in before.get("details", {}).items():
        if write._mismatches(value, after.get("details", {}).get(key)):
            changed.append(f"details.{key}")
    for system, value in before.get("classifications", {}).items():
        if after.get("classifications", {}).get(system) != value:
            changed.append(f"classification.{system}")
    properties = [
        prop
        for prop, value in before.get("properties", {}).items()
        if after.get("properties", {}).get(prop) != value
    ]
    return changed, properties


async def _plan(client, request: ParameterRequest, port, operation):
    changes = request.changes
    pairs = [(c.element_guid, c.target, c.name) for c in changes]
    if len(set(pairs)) != len(pairs):
        raise ValueError("Each element/target/parameter may appear once.")
    guids = list(dict.fromkeys(c.element_guid for c in changes))
    edit._unique(guids, MAX_ELEMENTS)
    port, target, details = await edit._editable(client, guids, port)
    tapir = gdl.tapir_version(target)
    kinds = {g: row["type"] for g, row in zip(guids, details, strict=True)}
    problems = []
    for c in changes:
        kind = kinds[c.element_guid]
        if c.target == "gdl" and kind not in gdl.GDL_OWNER_TYPES:
            problems.append(f"{c.element_guid} {c.name}: {kind} has no GDL parameters in Tapir")
        if c.target == "marker" and (kind not in gdl.MARKER_TYPES or tapir < gdl.MARKER_SINCE):
            problems.append(f"{c.element_guid} {c.name}: marker needs a door/window, Tapir 1.7.1")
    if request.run_parameter_script and tapir < gdl.SCRIPT_SINCE:
        problems.append("run_parameter_script needs Tapir 1.7.3 (RunParameterScriptOfElements)")
    if problems:
        raise ValueError("; ".join(problems))
    wanted = {t: [g for g in guids if any(c.element_guid == g and c.target == t
              for c in changes)] for t in ("gdl", "marker")}  # fmt: skip
    current = {
        "gdl": await _rows(
            client, port, "GetGDLParametersOfElements", "gdlParametersOfElements", wanted["gdl"]
        ),
        "marker": await _rows(
            client,
            port,
            "GetMarkerParametersOfElements",
            "markerParametersOfElements",
            wanted["marker"],
        ),
    }
    identity = await _identity(client, port, guids)
    items = []
    for index, guid in enumerate(guids):
        row = details[index]
        item = {
            "index": index,
            "status": "ready",
            "element_guid": guid,
            "type": row["type"],
            "floorIndex": row.get("floorIndex"),
            "layerIndex": row.get("layerIndex"),
            "changes": [],
            "gdl_payload": [],
            "marker_payload": [],
            "identity_before": identity[guid],
            "snapshot": {},
        }
        for target_name in ("gdl", "marker"):
            raw = current[target_name].get(guid)
            if raw is None:
                continue
            parameters = raw.get("parameters") if isinstance(raw, dict) else None
            if not isinstance(parameters, list):
                error = raw.get("error") if isinstance(raw, dict) else raw
                problems.append(f"{guid}: cannot read {target_name} parameters: {error}")
                continue
            item["snapshot"][target_name] = {
                p["name"]: p.get("value") for p in parameters if isinstance(p, dict)
            }
            named = gdl.by_name(parameters)
            for c in changes:
                if c.element_guid != guid or c.target != target_name:
                    continue
                found = named.get(c.name)
                if found is None:
                    problems.append(
                        f"{guid} {target_name}.{c.name}: "
                        + ("name is duplicated" if c.name in named else "no such parameter")
                    )
                    continue
                try:
                    expected, wire = gdl.coerce(found, c.value, tapir)
                    if target_name == "marker" and isinstance(expected, list):
                        raise ValueError("marker array parameters are not supported by Tapir")
                except ValueError as exc:
                    problems.append(f"{guid} {target_name}.{c.name}: {exc}")
                    continue
                described = gdl.describe([found])[0]
                unchanged = gdl.same(expected, found.get("value"))
                item["changes"].append(
                    {
                        "target": target_name,
                        "name": c.name,
                        "description": described["description"],
                        "type": described["type"],
                        "unit": described["unit"],
                        "before": found.get("value"),
                        "before_description": described["value_description"],
                        "requested": expected,
                        "status": "unchanged" if unchanged else "ready",
                    }
                )
                if not unchanged:
                    item[f"{target_name}_payload"].append({"name": c.name, "value": wire})
        if not item["gdl_payload"] and not item["marker_payload"]:
            item["status"] = "unchanged"
        items.append(item)
    if problems:
        raise ValueError("; ".join(problems))
    return {
        "operation": operation,
        "target": target,
        "run_parameter_script": request.run_parameter_script,
        "items": items,
    }


async def _send(client, receipt, items, command, key, payload_key, field):
    """One undoable Tapir command for these items; returns those Archicad accepted."""
    port, timeout = receipt["target"]["port"], receipt["write_timeout_seconds"]
    body = [{"elementId": {"guid": i["element_guid"]}, field: i[payload_key]} for i in items]
    try:
        raw = await client.tapir(port, command, {key: body}, timeout=timeout)
        rows = raw.get("executionResults")
        if not isinstance(rows, list) or len(rows) != len(items):
            raise ValueError(f"Unexpected {command} response cardinality.")
    except (ArchicadError, ValueError) as exc:
        for item in items:
            item.update(status="unknown", error=f"{command}: {exc}")
        receipt["warning"] = (
            "Outcome unknown; the read-back below shows what Archicad holds now. "
            "Inspect before any new request; never retry this token."
        )
        return []
    receipt["undo_steps"] += 1
    accepted = []
    for item, row in zip(items, rows, strict=True):
        item.setdefault("write_responses", {})[command] = row
        if isinstance(row, dict) and row.get("success") is True:
            accepted.append(item)
        else:
            error = row.get("error") if isinstance(row, dict) else row
            item.update(status="failed", error=error or f"{command} did not succeed.")
    return accepted


def _check(item, target_name, raw):
    """Compare one target's read-back with the request and list script side effects."""
    parameters = raw.get("parameters") if isinstance(raw, dict) else None
    if not isinstance(parameters, list):
        return [f"{target_name}: read-back failed"]
    named = gdl.by_name(parameters)
    mismatches = []
    for change in item["changes"]:
        if change["target"] != target_name:
            continue
        actual = named.get(change["name"]) or {}
        change["after"] = actual.get("value")
        change["after_description"] = actual.get("valueDescription")
        if gdl.same(change["requested"], actual.get("value")):
            if change["status"] != "unchanged":
                change["status"] = "verified"
        else:
            change["status"] = "not_applied"
            change["error"] = (
                "Archicad holds another value after the write; the parameter script or "
                "the library part's limits may have adjusted it."
            )
            mismatches.append(f"{target_name}.{change['name']}")
    requested = {c["name"] for c in item["changes"] if c["target"] == target_name}
    before = item["snapshot"].get(target_name, {})
    item.setdefault("dependent_changes", []).extend(
        {"target": target_name, "name": name, "before": before[name],
         "after": (named.get(name) or {}).get("value")}
        for name in before
        if name not in requested and name in named and named[name] is not None
        and not gdl.same(before[name], named[name].get("value"))
    )  # fmt: skip
    return mismatches


async def _dispatch(client, receipt):
    receipt["undo_steps"] = 0
    port, timeout = receipt["target"]["port"], receipt["write_timeout_seconds"]
    items = [i for i in receipt["items"] if i["status"] == "ready"]
    for item in receipt["items"]:
        if item["status"] == "unchanged":
            item["status"] = "verified"
            item["note"] = "Every requested value was already set; nothing was sent."
    gdl_items = [i for i in items if i["gdl_payload"]]
    written = await _send(
        client,
        receipt,
        gdl_items,
        "SetGDLParametersOfElements",
        "elementsWithGDLParameters",
        "gdl_payload",
        "gdlParameters",
    )
    unknown = any(i["status"] == "unknown" for i in items)
    if unknown:
        for item in items:
            if item["status"] == "ready" and item not in written:
                item.update(status="failed", not_attempted=True,
                            error="Not sent: an earlier step has an unknown outcome.")  # fmt: skip
    marker_items = [
        i for i in items if i["marker_payload"] and i["status"] == "ready" and not unknown
    ]
    if marker_items:
        await _send(
            client,
            receipt,
            marker_items,
            "SetMarkerParametersOfElements",
            "elementsWithMarkerParameters",
            "marker_payload",
            "markerParameters",
        )
    # A GDL write that Archicad accepted is read back even if its marker step failed.
    touched = [i for i in items if i["status"] in ("ready", "unknown") or i in written]
    if receipt.get("run_parameter_script") and written and not unknown:
        try:
            raw = await client.tapir(
                port,
                "RunParameterScriptOfElements",
                {"elements": read.element_ids([i["element_guid"] for i in written])},
                timeout=timeout,
            )
            receipt["undo_steps"] += 1
            receipt["parameter_script"] = raw.get("executionResults")
        except ArchicadError as exc:
            receipt["parameter_script"] = {"error": str(exc)}
    if not touched:
        return
    guids = [i["element_guid"] for i in touched]
    try:
        after_gdl = await _rows(
            client,
            port,
            "GetGDLParametersOfElements",
            "gdlParametersOfElements",
            [i["element_guid"] for i in touched if i["snapshot"].get("gdl") is not None],
            timeout,
        )
        after_marker = await _rows(
            client,
            port,
            "GetMarkerParametersOfElements",
            "markerParametersOfElements",
            [i["element_guid"] for i in touched if i["snapshot"].get("marker") is not None],
            timeout,
        )
        identity = await _identity(client, port, guids, timeout)
    except (ArchicadError, ValueError, KeyError, TypeError) as exc:
        receipt["verification_error"] = str(exc)
        for item in touched:
            if item["status"] == "ready":
                item["status"] = "unverified"
        return
    for item in touched:
        guid = item["element_guid"]
        mismatches = []
        if guid in after_gdl:
            mismatches += _check(item, "gdl", after_gdl[guid])
        if guid in after_marker:
            mismatches += _check(item, "marker", after_marker[guid])
        changed, properties = _identity_mismatches(item["identity_before"], identity[guid])
        item["identity_after"] = identity[guid]
        if changed:
            item["identity_changed"] = changed
            mismatches += [f"identity.{c}" for c in changed]
        if properties:
            item["unrequested_property_changes"] = properties
        if item["status"] in ("unknown", "failed"):
            item["observed"] = f"read back after a {item['status']} step; status kept"
            continue
        if receipt.get("parameter_script") is not None and not isinstance(
            receipt["parameter_script"], list
        ):
            mismatches.append("parameter_script")
        item["status"] = "verification_failed" if mismatches else "verified"
        if mismatches:
            item["mismatches"] = mismatches


async def set_element_parameters(
    client: ArchicadClient,
    changes: list[dict | ParameterChange],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
    run_parameter_script: bool = False,
) -> dict:
    """Preview/apply GDL and marker parameter changes on up to 20 existing elements.

    The preview lists only the requested differences, validated against type, flags,
    lock state, options, limits and array shape. Apply needs the explicit port and the
    single-use token; all GDL changes go in one undoable command, markers in a second.
    Each value is read back after the parameter script; other parameters it changed are
    listed as dependent_changes. GUID, host wall, placement, layer and classification are
    compared before/after. Never saves: use begin_model_task/finish_model_task.
    """
    request = ParameterRequest.model_validate(
        {
            "changes": [
                c.model_dump() if isinstance(c, ParameterChange) else deepcopy(c) for c in changes
            ],
            "run_parameter_script": run_parameter_script,
        }
    )
    return await write._write(
        client,
        request,
        port,
        dry_run,
        confirmation_token,
        "set_element_parameters",
        planner_override=_plan,
        dispatcher_override=_dispatch,
        completion_note="No project was saved. Archicad Undo reverts each native step "
        "(see undo_steps); finish_model_task saves the working PLN.",
    )
