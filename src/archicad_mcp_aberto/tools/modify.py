"""Edits of existing slabs, columns, beams, windows, doors, objects and morphs (Tapir Modify*).

Every tool follows modify_walls: a dry run first, a single-use token and the explicit
port to apply, per-element receipts and a read-back of each changed field. Fields are
Tapir's native camelCase names, in metres. Nothing is ever saved.

Levels are offsets from the element's own story. Tapir 1.7.0 takes an absolute
zCoordinate for slabs and objects and picks the story from it, so a change that would
move the element to another story is refused instead of silently re-homing it.
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import edit, read, roofs, texts, write
from archicad_mcp_aberto.tools import morphs as boxes

MAX_EDITS = 50


class _Edit(write.InputModel):
    guid: str

    @field_validator("guid")
    @classmethod
    def canonical_guid(cls, value):
        return str(UUID(value)).upper()

    @model_validator(mode="after")
    def has_changes(self):
        if not self.model_dump(exclude={"guid"}, exclude_none=True):
            raise ValueError("Supply at least one field to modify.")
        return self


class SlabModify(_Edit):
    thickness: write.Positive | None = None
    level: float | None = None


class ColumnModify(_Edit):
    origin: write.Point | None = None
    bottomOffset: float | None = None
    height: write.Positive | None = None
    width: write.Positive | None = None
    depth: write.Positive | None = None


class BeamModify(_Edit):
    begCoordinate: write.Point | None = None
    endCoordinate: write.Point | None = None
    level: float | None = None
    width: write.Positive | None = None
    height: write.Positive | None = None


class OpeningModify(_Edit):
    width: write.Positive | None = None
    height: write.Positive | None = None
    sillHeight: float | None = None
    centerOffset: Annotated[float, Field(ge=0)] | None = None


class Dimensions(write.InputModel):
    x: write.Positive
    y: write.Positive
    z: write.Positive


class ObjectModify(_Edit):
    origin: write.Point | None = None
    level: float | None = None
    dimensions: Dimensions | None = None


class LampModify(ObjectModify):
    lightIsOn: bool | None = None


class RoofModify(_Edit):
    thickness: write.Positive | None = None
    level: float | None = None
    eavesOverhang: Annotated[float, Field(ge=0)] | None = None
    levels: Annotated[list[roofs.RoofLevel], Field(min_length=1, max_length=16)] | None = None

    @model_validator(mode="after")
    def ordered_levels(self):
        heights = [level.height for level in self.levels or []]
        if heights != sorted(heights):
            raise ValueError("Roof levels must be ordered by non-decreasing height.")
        return self


class TextModify(_Edit):
    text: Annotated[str, Field(min_length=1, max_length=2000)] | None = None
    position: write.Point | None = None
    angle: float | None = None
    heightMm: write.Positive | None = None
    justification: Literal["Left", "Center", "Right", "Full"] | None = None

    @field_validator("text")
    @classmethod
    def visible(cls, value):
        if value is not None and not value.strip():
            raise ValueError("text must not be blank.")
        return value if value is None else texts._lines(value)


class LabelModify(_Edit):
    text: Annotated[str, Field(min_length=1, max_length=2000)] | None = None
    height_mm: write.Positive | None = None

    @field_validator("text")
    @classmethod
    def visible(cls, value):
        if value is not None and not value.strip():
            raise ValueError("text must not be blank.")
        return value if value is None else texts._lines(value)


class MorphSize(write.InputModel):
    x: boxes.Size
    y: boxes.Size
    z: boxes.Size


class MorphModify(_Edit):
    size: MorphSize | None = None
    buildingMaterial: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    surface: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    castShadow: bool | None = None
    receiveShadow: bool | None = None


def _box_size(body: Any) -> dict | None:
    """The size of a create_morphs box body (corner at the origin), else None."""
    if not isinstance(body, dict) or body.get("bodyType") != "Solid":
        return None
    vertices, polygons = body.get("vertices"), body.get("polygons")
    if not isinstance(vertices, list) or len(vertices) != 8:
        return None
    if not isinstance(polygons, list) or len(polygons) != len(boxes.FACES):
        return None
    try:
        size = {k: max(float(v[k]) for v in vertices) for k in "xyz"}
        low = {k: min(float(v[k]) for v in vertices) for k in "xyz"}
    except (KeyError, TypeError, ValueError):
        return None
    if any(abs(low[k]) > boxes.TOLERANCE or size[k] <= 0 for k in "xyz"):
        return None

    def snap(value: float, top: float) -> float | None:
        if abs(value) <= boxes.TOLERANCE:
            return 0
        return top if abs(value - top) <= boxes.TOLERANCE else None

    found = {tuple(snap(float(v[k]), size[k]) for k in "xyz") for v in vertices}
    corners = {(x, y, z) for x in (0, size["x"]) for y in (0, size["y"]) for z in (0, size["z"])}
    return size if found == corners else None


async def _morph_attributes(client, port, edits) -> dict:
    """Attribute name -> GUID for the building materials and surfaces the edits name."""
    out: dict[str, dict[str, str]] = {}
    for field, kind in (("buildingMaterial", "BuildingMaterial"), ("surface", "Surface")):
        wanted = {getattr(e, field) for e in edits if getattr(e, field) is not None}
        if not wanted:
            continue
        response = await client.tapir(port, "GetAttributesByType", {"attributeType": kind})
        rows = response.get("attributes")
        if not isinstance(rows, list):
            raise ValueError(f"Cannot read the {kind} attributes.")
        names = {}
        for row in rows:
            guid = _guid_of(row.get("attributeId")) if isinstance(row, dict) else None
            if guid and isinstance(row.get("name"), str):
                names.setdefault(row["name"], guid)
        out[field] = {}
        for name in wanted:
            found = [n for n in names if n == name] or [
                n for n in names if n.strip().casefold() == name.strip().casefold()
            ]
            if len(found) != 1:
                problem = "is ambiguous" if found else "does not exist"
                raise ValueError(f"{kind} {name!r} {problem}.")
            out[field][name] = names[found[0]]
    return out


def _guid_of(value: Any) -> str | None:
    try:
        return str(UUID(value["guid"])).upper()
    except (KeyError, TypeError, ValueError):
        return None


def _morph(change, row, target, label, extra):
    details, changes = row["details"], change.model_dump(exclude={"guid"}, exclude_none=True)
    parameters, expected = {}, {}
    if "size" in changes:
        if _box_size(details.get("body")) is None:
            raise ValueError(
                f"{label}: only a box morph (as create_morphs makes) can be resized; "
                "Tapir replaces the whole body."
            )
        box = boxes.MorphCreate(
            base_point={"x": 0, "y": 0, "z": 0},
            size_x=changes["size"]["x"],
            size_y=changes["size"]["y"],
            size_z=changes["size"]["z"],
            floor_index=0,
        )
        parameters["body"] = boxes._body(box)
        expected["body"] = {"bodyType": "Solid", "isClosed": True}
    for field, key in (("buildingMaterial", "buildingMaterialId"), ("surface", "surfaceId")):
        if field in changes:
            attribute = {"guid": extra[field][changes[field]]}
            parameters[key] = attribute
            expected[key] = attribute
    for key in ("castShadow", "receiveShadow"):
        if key in changes:
            parameters[key] = expected[key] = changes[key]
    return changes, parameters, expected


def _label(change, row, target, label, extra):
    details = row["details"]
    if details.get("labelClass") != "Text":
        raise ValueError(f"{label}: only Text labels are supported; Symbol labels are refused.")
    changes = change.model_dump(exclude={"guid"}, exclude_none=True)
    if not isinstance(details.get("text"), str):
        raise ValueError(f"{label}: cannot read the current text.")
    # Positions and associations cannot be changed through ModifyLabels 1.7.0.
    expected = {"labelClass": "Text", "text": changes.get("text", texts._lines(details["text"]))}
    for key in ("begCoordinate", "midCoordinate", "endCoordinate", "ownerElementId"):
        if key in details:
            expected[key] = deepcopy(details[key])
    parameters = {}
    if "text" in changes:
        parameters["text"] = changes["text"]
    if "height_mm" in changes:
        style = details.get("style")
        if not isinstance(style, dict):
            raise ValueError(f"{label}: cannot read the current style.")
        _number(style, "height", label)
        parameters["style"] = {"height": changes["height_mm"]}
        expected["style"] = {"height": changes["height_mm"]}
    return changes, parameters, expected


def _number(details, key, label):
    value = details.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{label}: cannot read the current {key}.")
    return value


def _story(target, row):
    return next(s for s in target["stories"] if s["index"] == row["floorIndex"])


def _same_story(target, row, z, label):
    """Mirror Tapir's GetFloorIndexAndOffset: the highest story at or below z wins."""
    found = None
    for story in sorted(target["stories"], key=lambda s: s["index"]):
        if story["level"] > z:
            break
        found = story
    if (found["index"] if found else 0) != row["floorIndex"]:
        raise ValueError(
            f"{label}: that level would move the element to another story. "
            "Keep it at or above its story level and below the next story."
        )


def _section(changes, details, first, second, label):
    """Linked (or round) sections keep both sizes equal; send and expect both."""
    sizes = {k: changes[k] for k in (first, second) if k in changes}
    if not sizes:
        return {}
    linked = details.get("circleBased") is True or details.get("isWidthAndHeightLinked") is True
    if linked:
        if len(set(sizes.values())) != 1:
            raise ValueError(f"{label}: {first} and {second} are linked; pass one size.")
        size = next(iter(sizes.values()))
        return {first: size, second: size}
    return sizes


def _slab(change, row, target, label, extra):
    details, changes = row["details"], change.model_dump(exclude={"guid"}, exclude_none=True)
    parameters, expected = {}, {}
    if "thickness" in changes:
        if details.get("structureType") != "Basic":
            raise ValueError(f"{label}: direct thickness changes require a Basic slab.")
        _number(details, "thickness", label)
        parameters["thickness"] = expected["thickness"] = changes["thickness"]
    if "level" in changes:
        _number(details, "level", label)
        z = _story(target, row)["level"] + changes["level"]
        _same_story(target, row, z, label)
        parameters["zCoordinate"] = z
        expected.update(level=changes["level"], zCoordinate=z)
    return changes, parameters, expected


def _column(change, row, target, label, extra):
    details, changes = row["details"], change.model_dump(exclude={"guid"}, exclude_none=True)
    parameters, expected = {}, {}
    if "origin" in changes:
        parameters["origin"] = expected["origin"] = changes["origin"]
    if "bottomOffset" in changes:
        _number(details, "bottomOffset", label)
        parameters["bottomOffset"] = changes["bottomOffset"]
        expected.update(
            bottomOffset=changes["bottomOffset"],
            zCoordinate=_story(target, row)["level"] + changes["bottomOffset"],
        )
    if "height" in changes:
        _number(details, "height", label)
        parameters["height"] = expected["height"] = changes["height"]
        expected["relativeTopStory"] = 0  # Tapir unlinks the top when height is set.
    section = _section(changes, details, "width", "depth", label)
    for key in section:
        _number(details, key, label)
    parameters.update(section)
    expected.update(section)
    return changes, parameters, expected


def _beam(change, row, target, label, extra):
    details, changes = row["details"], change.model_dump(exclude={"guid"}, exclude_none=True)
    arc = details.get("arcAngle")
    if (
        details.get("beamShape") != "Straight"
        or not isinstance(arc, (int, float))
        or isinstance(arc, bool)
        or not math.isfinite(arc)
        or abs(arc) > 1e-9
    ):
        raise ValueError(f"{label}: curved beams are refused.")
    parameters, expected = {}, {}
    start = changes.get("begCoordinate", details.get("begCoordinate"))
    end = changes.get("endCoordinate", details.get("endCoordinate"))
    if not isinstance(start, dict) or not isinstance(end, dict):
        raise ValueError(f"{label}: beam endpoints are required for safe editing.")
    start = write.Point.model_validate(start).model_dump()
    end = write.Point.model_validate(end).model_dump()
    if math.hypot(start["x"] - end["x"], start["y"] - end["y"]) < 1e-6:
        raise ValueError(f"{label}: the resulting beam would have zero length.")
    for key in ("begCoordinate", "endCoordinate"):
        if key in changes:
            parameters[key] = expected[key] = changes[key]
    if "level" in changes:
        _number(details, "level", label)
        parameters["level"] = changes["level"]
        expected.update(
            level=changes["level"], zCoordinate=_story(target, row)["level"] + changes["level"]
        )
    section = _section(changes, details, "width", "height", label)
    for key in section:
        _number(details, key, label)
    parameters.update(section)
    expected.update(section)
    if expected:
        expected.update(beamShape="Straight", arcAngle=0.0)
    return changes, parameters, expected


def _opening(change, row, target, label, extra):
    details, changes = row["details"], change.model_dump(exclude={"guid"}, exclude_none=True)
    owner = details.get("ownerElementId")
    if details.get("ownerElementType") != "Wall" or not isinstance(owner, dict):
        raise ValueError(f"{label}: only openings in walls are supported.")
    for key in changes:
        _number(details, key, label)
    if "centerOffset" in changes:
        wall = extra.get(str(owner.get("guid", "")).upper())
        wall_details = wall.get("details") if isinstance(wall, dict) else None
        if not isinstance(wall_details, dict) or wall_details.get("geometryType") != "Straight":
            raise ValueError(f"{label}: moving an opening needs its straight owner wall.")
        begin, end = wall_details.get("begCoordinate"), wall_details.get("endCoordinate")
        if not isinstance(begin, dict) or not isinstance(end, dict):
            raise ValueError(f"{label}: the owner wall has no reference line coordinates.")
        length = math.hypot(end["x"] - begin["x"], end["y"] - begin["y"])
        if changes["centerOffset"] > length + 1e-6:
            raise ValueError(
                f"{label}: centerOffset {changes['centerOffset']} m is past the wall end "
                f"({length:.3f} m long)."
            )
    return changes, dict(changes), dict(changes)


def _object(change, row, target, label, extra):
    details, changes = row["details"], change.model_dump(exclude={"guid"}, exclude_none=True)
    parameters, expected = {}, {}
    if "origin" in changes or "level" in changes:
        origin = details.get("origin")
        if not isinstance(origin, dict):
            raise ValueError(f"{label}: cannot read the current origin.")
        coordinates = {
            "x": changes.get("origin", origin)["x"],
            "y": changes.get("origin", origin)["y"],
            "z": (
                _story(target, row)["level"] + changes["level"]
                if "level" in changes
                else _number(origin, "z", label)
            ),
        }
        _same_story(target, row, coordinates["z"], label)
        parameters["coordinates"] = coordinates
        expected["origin"] = coordinates
    if "dimensions" in changes:
        if not isinstance(details.get("dimensions"), dict):
            raise ValueError(f"{label}: cannot read the current dimensions.")
        parameters["dimensions"] = changes["dimensions"]
        # Tapir 1.7.0 changes x and y but not the height, and reads dimensions.z as 0
        # (live, AC30 build 3001 BRA, 14/10/2026): the height is set through ZZYZX.
        expected["dimensions"] = {k: changes["dimensions"][k] for k in ("x", "y")}
    return changes, parameters, expected


def _lamp(change, row, target, label, extra):
    changes, parameters, expected = _object(change, row, target, label, extra)
    if "lightIsOn" in changes:
        # Tapir 1.7.0 writes lightIsOn; its own source says lightColor is discarded.
        parameters["lightIsOn"] = expected["lightIsOn"] = changes["lightIsOn"]
    return changes, parameters, expected


def _roof(change, row, target, label, extra):
    details, changes = row["details"], change.model_dump(exclude={"guid"}, exclude_none=True)
    if details.get("roofClass") != "MultiPlane":
        raise ValueError(f"{label}: Tapir 1.7.0 edits only multi-plane roofs.")
    parameters, expected = {}, {}
    if "thickness" in changes:
        if details.get("structureType") != "Basic":
            raise ValueError(f"{label}: direct thickness changes require a Basic roof.")
        _number(details, "thickness", label)
        parameters["thickness"] = expected["thickness"] = changes["thickness"]
    if "level" in changes:
        _number(details, "level", label)
        z = _story(target, row)["level"] + changes["level"]
        _same_story(target, row, z, label)
        parameters["level"] = z  # Tapir takes the roof level as absolute Z here.
        expected.update(level=changes["level"], zCoordinate=z)
    if "eavesOverhang" in changes:
        _number(details, "eavesOverhang", label)
        parameters["eavesOverhang"] = expected["eavesOverhang"] = changes["eavesOverhang"]
    if "levels" in changes:
        parameters["levels"] = [
            {"levelHeight": v["height"], "levelAngle": v["angle"]} for v in changes["levels"]
        ]
        expected["levels"] = changes["levels"]
    return changes, parameters, expected


def _text(change, row, target, label, extra):
    details, changes = row["details"], change.model_dump(exclude={"guid"}, exclude_none=True)
    parameters, expected, style = {}, {}, {}
    if "position" in changes:
        # Keep the text on its story: an explicit floorIndex wins over the z in ModifyTexts.
        parameters["coordinate"] = {**changes["position"], "z": _story(target, row)["level"]}
        parameters["floorIndex"] = row["floorIndex"]
        expected["position"] = changes["position"]
    if "text" in changes:
        parameters["text"] = expected["text"] = changes["text"]
    for key, native in (("angle", "angle"), ("heightMm", "height"), ("justification", None)):
        if key in changes:
            native = native or key
            if native != "justification":
                _number(details, native, label)
            style[native] = expected[native] = changes[key]
    if style:
        parameters["style"] = style
    return changes, parameters, expected


async def _owner_walls(client, port, rows):
    guids = []
    for row in rows:
        details = row.get("details")
        owner = details.get("ownerElementId") if isinstance(details, dict) else None
        if isinstance(owner, dict) and isinstance(owner.get("guid"), str):
            guids.append(owner["guid"].upper())
    guids = list(dict.fromkeys(guids))
    if not guids:
        return {}
    response = await client.tapir(
        port, "GetDetailsOfElements", {"elements": read.element_ids(guids), "fields": ["details"]}
    )
    walls = response.get("detailsOfElements")
    if not isinstance(walls, list) or len(walls) != len(guids):
        raise ValueError("Unexpected owner wall details response.")
    return dict(zip(guids, walls, strict=True))


# Library part edits whose height goes through ZZYZX after the Modify command.
HEIGHTS = ("modify_objects", "modify_lamps")
# operation -> (element types accepted, Tapir command, list key, field planner)
SPECS = {
    "modify_slabs": (("Slab",), "ModifySlabs", "slabsWithDetails", _slab),
    "modify_columns": (("Column",), "ModifyColumns", "columnsWithDetails", _column),
    "modify_beams": (("Beam",), "ModifyBeams", "beamsWithDetails", _beam),
    "modify_windows": (("Window",), "ModifyWindows", "windowsWithDetails", _opening),
    "modify_doors": (("Door",), "ModifyDoors", "doorsWithDetails", _opening),
    "modify_objects": (("Object",), "ModifyObjects", "objectsWithDetails", _object),
    "modify_lamps": (("Lamp",), "ModifyLamps", "lampsWithDetails", _lamp),
    "modify_roofs": (("Roof",), "ModifyRoofs", "roofsWithDetails", _roof),
    "modify_texts": (("Text",), "ModifyTexts", "textsWithDetails", _text),
    "modify_labels": (("Label",), "ModifyLabels", "labelsWithDetails", _label),
    "modify_morphs": (("Morph",), "ModifyMorphs", "morphsWithDetails", _morph),
}


async def _plan(client, edits, port, operation):
    types, _, _, fields = SPECS[operation]
    port, target, rows = await edit._editable(client, [e.guid for e in edits], port)
    extra: dict[str, Any] = {}
    if operation in ("modify_windows", "modify_doors"):
        extra = await _owner_walls(client, port, rows)
    if operation == "modify_morphs":
        extra = await _morph_attributes(client, port, edits)
    items = []
    for index, (change, row) in enumerate(zip(edits, rows, strict=True)):
        label = f"{types[0]} {index} ({change.guid})"
        if row["type"] not in types or not isinstance(row.get("details"), dict):
            raise ValueError(f"{label}: is a {row['type']}, not a {types[0]} with details.")
        changes, parameters, expected = fields(change, row, target, label, extra)
        if operation in HEIGHTS and "dimensions" in changes:
            height = await _height_parameter(client, port, change.guid, label)
            try:
                height["value"] = edit._gdl_value(height["before"], changes["dimensions"]["z"])
            except ValueError as exc:
                raise ValueError(f"{label}: cannot set the height (ZZYZX): {exc}") from None
            extra_item = {"height": height}
        else:
            extra_item = {}
        items.append(
            {
                "index": index,
                "status": "ready",
                "element_guid": change.guid,
                "type": row["type"],
                "floorIndex": row.get("floorIndex"),
                "layerIndex": row.get("layerIndex"),
                "before": deepcopy(row),
                "new": changes,
                "expected": expected,
                "parameters": {"elementId": {"guid": change.guid}, **parameters},
                **extra_item,
            }
        )
    return {"operation": operation, "target": target, "items": items}


async def _height_parameter(client, port, guid, label) -> dict:
    rows = await edit._gdl_rows(client, port, [guid])
    parameters = rows[guid].get("parameters") if isinstance(rows[guid], dict) else None
    found = [
        p
        for p in (parameters if isinstance(parameters, list) else [])
        if isinstance(p, dict) and str(p.get("name", "")).casefold() == "zzyzx"
    ]
    if len(found) != 1 or "value" not in found[0]:
        raise ValueError(f"{label}: the library part has no ZZYZX height parameter.")
    return {"name": found[0]["name"], "before": deepcopy(found[0])}


async def _set_heights(client, receipt) -> None:
    """Second step of modify_objects and modify_lamps: ZZYZX by Set/GetGDLParameters."""
    items = [
        i
        for i in receipt["items"]
        if "height" in i and i["status"] in ("verified", "verification_failed")
    ]
    if not items:
        return
    port, timeout = receipt["target"]["port"], receipt["write_timeout_seconds"]
    payload = [
        {
            "elementId": {"guid": i["element_guid"]},
            "gdlParameters": [{"name": i["height"]["name"], "value": i["height"]["value"]}],
        }
        for i in items
    ]
    try:
        raw = await client.tapir(
            port,
            "SetGDLParametersOfElements",
            {"elementsWithGDLParameters": payload},
            timeout=timeout,
        )
        rows = raw.get("executionResults")
        if not isinstance(rows, list) or len(rows) != len(items):
            raise ValueError("Unexpected height response cardinality.")
    except (ArchicadError, ValueError) as exc:
        for item in items:
            item.update(status="unknown", height_error=str(exc))
        receipt["warning"] = "Height outcome unknown; inspect Archicad. Never retry this token."
        return
    written = []
    for item, row in zip(items, rows, strict=True):
        item["height"]["write_response"] = row
        if isinstance(row, dict) and row.get("success") is True:
            written.append(item)
        else:
            error = row.get("error") if isinstance(row, dict) else None
            item.update(status="verification_failed", height_error=error or "Height not set.")
            item["mismatches"] = item.get("mismatches", []) + ["gdl.ZZYZX"]
    if not written:
        return
    try:
        after = await edit._gdl_rows(client, port, [i["element_guid"] for i in written], timeout)
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        for item in written:
            item["status"] = "unverified"
        return
    for item in written:
        row = after[item["element_guid"]]
        parameters = row.get("parameters", []) if isinstance(row, dict) else []
        found = [p for p in parameters if p.get("name") == item["height"]["name"]]
        item["height"]["after"] = found[0] if len(found) == 1 else {}
        if write._mismatches({"value": item["height"]["value"]}, item["height"]["after"]):
            item["status"] = "verification_failed"
            item["mismatches"] = item.get("mismatches", []) + ["gdl.ZZYZX"]


def _check_sizes(receipt) -> None:
    """A resized morph's read-back body must be the requested box."""
    for item in receipt["items"]:
        wanted = item.get("new", {}).get("size")
        if wanted is None or item["status"] not in ("verified", "verification_failed"):
            continue
        details = (
            item.get("after", {}).get("details") if isinstance(item.get("after"), dict) else None
        )
        size = _box_size(details.get("body")) if isinstance(details, dict) else None
        item["size_after"] = size
        if size is None or any(abs(size[k] - wanted[k]) > boxes.TOLERANCE for k in "xyz"):
            item["status"] = "verification_failed"
            item["mismatches"] = item.get("mismatches", []) + ["details.body.size"]


def _detail_mismatches(expected, actual):
    """Angles compare on the circle, text in LF form, lists item by item."""
    differences = []
    for key, wanted in expected.items():
        found, path = actual.get(key), f"details.{key}"
        if key == "angle":
            if (
                not isinstance(found, (int, float))
                or isinstance(found, bool)
                or not math.isfinite(found)
                or abs(math.remainder(found - wanted, math.tau)) > 1e-7
            ):
                differences.append(path)
        elif key == "text":
            if not isinstance(found, str) or texts._lines(found) != wanted:
                differences.append(path)
        elif isinstance(wanted, list):
            if not isinstance(found, list) or len(found) != len(wanted):
                differences.append(path)
            else:
                for index, (a, b) in enumerate(zip(wanted, found, strict=True)):
                    differences += write._mismatches(a, b, f"{path}.{index}")
        else:
            differences += write._mismatches(wanted, found, path)
    return differences


async def _verify(client, receipt, items):
    response = await client.tapir(
        receipt["target"]["port"],
        "GetDetailsOfElements",
        {
            "elements": read.element_ids([i["element_guid"] for i in items]),
            "fields": write.DETAIL_FIELDS,
        },
        timeout=receipt["write_timeout_seconds"],
    )
    rows = response.get("detailsOfElements")
    if not isinstance(rows, list) or len(rows) != len(items):
        raise ValueError("Unexpected modified-element response cardinality.")
    for item, row in zip(items, rows, strict=True):
        item["after"] = row
        differences = write._mismatches(
            {
                "type": item["type"],
                "floorIndex": item["floorIndex"],
                "layerIndex": item["layerIndex"],
            },
            row,
        )
        details = row.get("details") if isinstance(row, dict) else None
        differences += _detail_mismatches(
            item["expected"], details if isinstance(details, dict) else {}
        )
        item["status"] = "verification_failed" if differences else "verified"
        if differences:
            item["mismatches"] = differences


async def _dispatch(client, receipt):
    _, command, key, _ = SPECS[receipt["operation"]]
    await edit._execute(client, receipt, command, key, _verify)
    if receipt["operation"] in HEIGHTS:
        await _set_heights(client, receipt)
    if receipt["operation"] == "modify_morphs":
        _check_sizes(receipt)


async def _modify(client, edits, model, port, dry_run, confirmation_token, operation):
    validated = [e if isinstance(e, model) else model.model_validate(e) for e in edits]
    edit._unique([e.guid for e in validated], MAX_EDITS)
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        operation,
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )


async def modify_slabs(
    client: ArchicadClient,
    slabs: list[dict | SlabModify],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/modify up to 50 slabs: thickness (Basic only) and level from its story."""
    return await _modify(
        client, slabs, SlabModify, port, dry_run, confirmation_token, "modify_slabs"
    )


async def modify_columns(
    client: ArchicadClient,
    columns: list[dict | ColumnModify],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/modify up to 50 columns: origin, bottomOffset, height, width, depth.

    Setting height unlinks the top story, as Tapir does. Round or linked sections take
    one size for both width and depth.
    """
    return await _modify(
        client, columns, ColumnModify, port, dry_run, confirmation_token, "modify_columns"
    )


async def modify_beams(
    client: ArchicadClient,
    beams: list[dict | BeamModify],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/modify up to 50 straight beams: endpoints, level, width, height."""
    return await _modify(
        client, beams, BeamModify, port, dry_run, confirmation_token, "modify_beams"
    )


async def modify_windows(
    client: ArchicadClient,
    windows: list[dict | OpeningModify],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/modify up to 50 windows in walls: width, height, sillHeight, centerOffset."""
    return await _modify(
        client, windows, OpeningModify, port, dry_run, confirmation_token, "modify_windows"
    )


async def modify_doors(
    client: ArchicadClient,
    doors: list[dict | OpeningModify],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/modify up to 50 doors in walls: width, height, sillHeight, centerOffset."""
    return await _modify(
        client, doors, OpeningModify, port, dry_run, confirmation_token, "modify_doors"
    )


async def modify_objects(
    client: ArchicadClient,
    objects: list[dict | ObjectModify],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/modify up to 50 objects: origin (x, y), level from its story, dimensions.

    dimensions.z sets the height through the ZZYZX GDL parameter; a part without it is refused.
    """
    return await _modify(
        client, objects, ObjectModify, port, dry_run, confirmation_token, "modify_objects"
    )


async def modify_lamps(
    client: ArchicadClient,
    lamps: list[dict | LampModify],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/modify up to 50 lamps: origin (x, y), level from its story, dimensions,
    lightIsOn.

    dimensions.z sets the height through the ZZYZX GDL parameter; a part without it is refused.
    """
    return await _modify(
        client, lamps, LampModify, port, dry_run, confirmation_token, "modify_lamps"
    )


async def modify_roofs(
    client: ArchicadClient,
    roofs: list[dict | RoofModify],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/modify up to 50 multi-plane roofs: thickness (Basic only), level from its
    story, eavesOverhang and levels (height, angle). Single-plane roofs are refused.
    """
    return await _modify(
        client, roofs, RoofModify, port, dry_run, confirmation_token, "modify_roofs"
    )


async def modify_texts(
    client: ArchicadClient,
    texts: list[dict | TextModify],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/modify up to 50 texts: text, position (stays on its story), angle,
    heightMm (paper millimetres) and justification.
    """
    return await _modify(
        client, texts, TextModify, port, dry_run, confirmation_token, "modify_texts"
    )


async def modify_labels(
    client: ArchicadClient,
    labels: list[dict | LabelModify],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/edit up to 50 Text labels: text and height_mm in paper millimetres.

    Tapir 1.7.0 ModifyLabels does not accept position or story changes. Symbol labels
    and unsupported fields are refused. Owner, position and story are preserved;
    content and size are read back. Never saves.
    """
    return await _modify(
        client, labels, LabelModify, port, dry_run, confirmation_token, "modify_labels"
    )


async def modify_morphs(
    client: ArchicadClient,
    morphs: list[dict | MorphModify],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/modify up to 50 morphs: size (x, y, z in metres, box morphs only),
    buildingMaterial and surface by name, castShadow and receiveShadow.

    Tapir rebuilds the whole body on a size change, so only a box as create_morphs
    makes is resized, keeping its corner. Moving and rotating stay with move_elements
    and rotate_elements.
    """
    return await _modify(
        client, morphs, MorphModify, port, dry_run, confirmation_token, "modify_morphs"
    )
