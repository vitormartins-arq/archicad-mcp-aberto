"""Safe edits of existing elements; SI units, shared confirmation and receipts."""

from __future__ import annotations

import math
from copy import deepcopy
from uuid import UUID

from pydantic import field_validator, model_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import read, write


async def _editable(client, guids, port):
    port, target, _ = await write._context(client, port)
    elements = read.element_ids(guids)
    result = await client.tapir(
        port, "GetDetailsOfElements", {"elements": elements, "fields": write.DETAIL_FIELDS}
    )
    rows = result.get("detailsOfElements")
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected element details response.")
    for guid, row in zip(guids, rows, strict=True):
        if not isinstance(row, dict) or "error" in row or row.get("type") in (None, "Unknown"):
            raise ValueError(f"Element {guid} does not exist or cannot be read.")
        if row.get("hotlinkId"):
            raise ValueError(f"Element {guid} belongs to a hotlink.")
    result = await client.tapir(
        port, "FilterElements", {"elements": elements, "filters": ["IsEditable"]}
    )
    editable = result.get("elements")
    if not isinstance(editable, list):
        raise ValueError("Unexpected editability response.")
    if set(guids) - {e["elementId"]["guid"].upper() for e in editable}:
        raise ValueError("Locked/non-editable elements are refused.")
    return port, target, rows


def _unique(guids, maximum):
    if not 1 <= len(guids) <= maximum:
        raise ValueError(f"Pass between 1 and {maximum} elements.")
    if len(set(guids)) != len(guids):
        raise ValueError("Each element may appear only once per call.")


async def _execute(client, receipt, command, key, verify):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    try:
        raw = await client.tapir(
            port, command, {key: [i["parameters"] for i in items]}, timeout=timeout
        )
    except ArchicadError as exc:
        for item in items:
            item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Outcome unknown; inspect Archicad. Never retry this token."
        return
    receipt["raw_response"] = raw
    rows = raw.get("executionResults")
    if not isinstance(rows, list) or len(rows) != len(items):
        for item in items:
            item.update(status="unknown", error="Unexpected execution response cardinality.")
        return
    good = []
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        if isinstance(row, dict) and row.get("success") is True:
            item["status"] = "unverified"
            good.append(item)
        elif isinstance(row, dict) and row.get("success") is False and "error" in row:
            item.update(status="failed", error=row["error"])
        else:
            item.update(status="unknown", error="Unexpected execution result.")
    if good:
        try:
            await verify(client, receipt, good)
        except (ArchicadError, ValueError, KeyError, TypeError) as exc:
            receipt["verification_error"] = str(exc)


class ElementRotation(write.InputModel):
    guid: str
    center: write.Point
    angle: float

    @field_validator("guid")
    @classmethod
    def canonical_guid(cls, value):
        return str(UUID(value)).upper()


def _point(point, center, angle):
    x, y = point["x"] - center["x"], point["y"] - center["y"]
    c, s = math.cos(angle), math.sin(angle)
    result = {**point, "x": center["x"] + c * x - s * y, "y": center["y"] + s * x + c * y}
    if not all(math.isfinite(result[k]) for k in ("x", "y")):
        raise ValueError("Nonfinite transformed coordinates.")
    return result


def _rotated_box(box, center, angle):
    points = [
        _point({"x": x, "y": y}, center, angle)
        for x in (box["xMin"], box["xMax"])
        for y in (box["yMin"], box["yMax"])
    ]
    return {
        "xMin": min(p["x"] for p in points),
        "xMax": max(p["x"] for p in points),
        "yMin": min(p["y"] for p in points),
        "yMax": max(p["y"] for p in points),
    }


async def _rotate_plan(client, rotations, port, operation):
    guids = [r.guid for r in rotations]
    port, target, rows = await _editable(client, guids, port)
    boxes = (await read.get_bounding_boxes(client, guids, port))["boundingBoxes"]
    items = []
    for index, (rotation, row, box) in enumerate(zip(rotations, rows, boxes, strict=True)):
        center, angle = rotation.center.model_dump(), math.remainder(rotation.angle, math.tau)
        begin = {"x": center["x"] + 1.0, "y": center["y"]}
        end = _point(begin, center, angle)
        if begin == center:
            raise ValueError("Rotation center is too large to construct a precise arc.")
        details = row.get("details", {})
        expected, angles = {}, []
        if all(isinstance(details.get(k), dict) for k in ("begCoordinate", "endCoordinate")):
            expected = {
                k: _point(details[k], center, angle) for k in ("begCoordinate", "endCoordinate")
            }
        elif isinstance(details.get("origin"), dict):
            angles = [k for k in ("angle", "axisRotationAngle") if k in details]
            if angles:
                expected = {"origin": _point(details["origin"], center, angle)}
                expected.update({k: details[k] + angle for k in angles})
        if expected:
            strategy = "details"
        else:
            # Rotating an AABB predicts a real AABB only at multiples of 90 degrees.
            if abs(angle / (math.pi / 2) - round(angle / (math.pi / 2))) > 1e-8:
                raise ValueError(
                    "Cannot verify this rotation: no coordinates/angle in details; "
                    "box-only verification requires multiples of pi/2."
                )
            if "box" not in box:
                raise ValueError("No bounding box available for rotation verification.")
            expected = _rotated_box(box["box"], center, angle)
            strategy = "box"
        items.append(
            {
                "index": index,
                "status": "ready",
                "element_guid": rotation.guid,
                "floorIndex": row.get("floorIndex"),
                "layerIndex": row.get("layerIndex"),
                "type": row["type"],
                "before": row,
                "verification": strategy,
                "expected": expected,
                "angle_fields": angles,
                "parameters": {
                    "elementId": {"guid": rotation.guid},
                    "copy": False,
                    "rotation": {"origin": center, "beginPoint": begin, "endPoint": end},
                },
            }
        )
    return {"operation": operation, "target": target, "items": items}


def _normalized_angle(angle):
    """The same direction in [0, 2*pi); values within 1e-7 of a full turn become 0."""
    normalized = angle % math.tau
    return 0.0 if math.tau - normalized < 1e-7 else normalized


async def _verify_rotation(client, receipt, items):
    port, timeout = receipt["target"]["port"], receipt["write_timeout_seconds"]
    guids = [i["element_guid"] for i in items]
    response = await client.tapir(
        port,
        "GetDetailsOfElements",
        {"elements": read.element_ids(guids), "fields": write.DETAIL_FIELDS},
        timeout=timeout,
    )
    rows = response.get("detailsOfElements")
    if not isinstance(rows, list) or len(rows) != len(items):
        raise ValueError("Unexpected rotation verification response.")
    box_items = [i for i in items if i["verification"] == "box"]
    boxes = {}
    if box_items:
        response = await client.command(
            port,
            "Get2DBoundingBoxes",
            {"elements": read.element_ids([i["element_guid"] for i in box_items])},
            timeout=timeout,
        )
        bounds = response.get("boundingBoxes2D")
        if not isinstance(bounds, list) or len(bounds) != len(box_items):
            raise ValueError("Unexpected box verification response.")
        boxes = {i["element_guid"]: b for i, b in zip(box_items, bounds, strict=True)}
    for item, row in zip(items, rows, strict=True):
        item["after"] = row
        differences = write._mismatches({"type": item["type"]}, row)
        if item["verification"] == "details":
            expected = deepcopy(item["expected"])
            actual = row.get("details", {})
            for key in item["angle_fields"]:
                wanted = expected.pop(key)
                found = actual.get(key)
                if (
                    not isinstance(found, (int, float))
                    or isinstance(found, bool)
                    or not math.isfinite(found)
                ):
                    differences.append(key)
                else:
                    if abs(math.remainder(found - wanted, math.tau)) > 1e-7:
                        differences.append(key)
                    normalized = _normalized_angle(found)
                    if normalized != found:
                        # Archicad can store a full turn as 2*pi (seen live on an Object);
                        # report the [0, 2*pi) value without writing it back.
                        item.setdefault("normalized_angles", {})[key] = normalized
            differences += write._mismatches(expected, actual)
        else:
            box = boxes[item["element_guid"]]
            item["after_box"] = box
            actual = box.get("boundingBox2D", {})
            differences += [
                k
                for k, wanted in item["expected"].items()
                if not isinstance(actual.get(k), (int, float))
                or not math.isfinite(actual[k])
                or abs(actual[k] - wanted) > 0.001
            ]
        item["status"] = "verification_failed" if differences else "verified"
        if differences:
            item["mismatches"] = differences


async def _rotate_dispatch(client, receipt):
    await _execute(client, receipt, "RotateElements", "elementsWithRotations", _verify_rotation)


async def rotate_elements(
    client: ArchicadClient,
    rotations: list[dict | ElementRotation],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Rotate up to 50 elements about XY centers, radians. Never copies or saves.

    Coordinates/angles verify arbitrary rotations; box-only verification needs pi/2
    multiples (1 mm). Refuses hotlinks, locked and nonexistent elements in preview.
    """
    validated = [
        r if isinstance(r, ElementRotation) else ElementRotation.model_validate(r)
        for r in rotations
    ]
    _unique([r.guid for r in validated], 50)
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "rotate_elements",
        planner_override=_rotate_plan,
        dispatcher_override=_rotate_dispatch,
    )


class GDLChange(write.InputModel):
    element_guid: str
    name: str
    value: str | bool | int | float

    @field_validator("element_guid")
    @classmethod
    def canonical_guid(cls, value):
        return str(UUID(value)).upper()

    @field_validator("name")
    @classmethod
    def nonblank(cls, value):
        if not value or value != value.strip():
            raise ValueError("Parameter name must be nonblank and unpadded.")
        return value


def _gdl_value(parameter, value):
    flags = parameter.get("flags", [])
    if not isinstance(flags, list) or not all(isinstance(f, str) for f in flags):
        raise ValueError("Unexpected GDL flags.")
    if parameter.get("isLocked") is True or set(flags) & {
        "Fixed",
        "Hidden",
        "HiddenFromScript",
        "Disabled",
    }:
        raise ValueError("Fixed, hidden, disabled or locked GDL parameters are refused.")
    if any(parameter.get(k, 0) for k in ("dimension1", "dimension2")) or isinstance(
        parameter.get("value"), (list, dict)
    ):
        raise ValueError("Array/dictionary GDL parameters are not supported.")
    kind = parameter.get("type")
    if kind in {"String", "Title"}:
        if not isinstance(value, str):
            raise ValueError("String GDL parameter requires text.")
    elif kind == "Boolean":
        if not isinstance(value, bool):
            raise ValueError("Boolean GDL parameter requires true/false.")
    elif kind == "LightSwitch":
        if not isinstance(value, bool):
            raise ValueError("LightSwitch requires true/false.")
        return "On" if value else "Off"
    elif kind in {
        "Integer",
        "PenColor",
        "LineType",
        "Material",
        "FillPattern",
        "BuildingMaterial",
        "Profile",
    }:
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("Integer GDL parameter requires an integer.")
    elif kind in {"Length", "Angle", "RealNumber", "Intensity", "RGBColor"}:
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise ValueError("Numeric GDL parameter requires a finite number.")
        value = float(value)
    else:
        raise ValueError(f"Unsupported GDL parameter type {kind!r}.")
    return value


async def _gdl_rows(client, port, guids, timeout=None):
    extra = {} if timeout is None else {"timeout": timeout}
    result = await client.tapir(
        port, "GetGDLParametersOfElements", {"elements": read.element_ids(guids)}, **extra
    )
    rows = result.get("gdlParametersOfElements")
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected GDL response cardinality.")
    return dict(zip(guids, rows, strict=True))


async def _gdl_plan(client, changes, port, operation):
    guids = list(dict.fromkeys(c.element_guid for c in changes))
    port, target, details = await _editable(client, guids, port)
    if any(row["type"] != "Object" for row in details):
        raise ValueError("Only Object GDL parameters are supported.")
    by_guid = dict(zip(guids, details, strict=True))
    rows = await _gdl_rows(client, port, guids)
    items = []
    for index, change in enumerate(changes):
        row = rows[change.element_guid]
        parameters = row.get("parameters") if isinstance(row, dict) else None
        if not isinstance(parameters, list):
            raise ValueError("Cannot read existing GDL parameters.")
        matches = [p for p in parameters if p.get("name") == change.name]
        if len(matches) != 1 or "value" not in matches[0]:
            raise ValueError(f"GDL parameter {change.name!r} does not exist or is ambiguous.")
        current = matches[0]
        value = _gdl_value(current, change.value)
        details = by_guid[change.element_guid]
        items.append(
            {
                "index": index,
                "status": "ready",
                "element_guid": change.element_guid,
                "floorIndex": details.get("floorIndex"),
                "layerIndex": details.get("layerIndex"),
                "before": deepcopy(current),
                "expected_type": current["type"],
                "parameters": {
                    "elementId": {"guid": change.element_guid},
                    "gdlParameters": [{"name": change.name, "value": value}],
                },
            }
        )
    return {"operation": operation, "target": target, "items": items}


async def _verify_gdl(client, receipt, items):
    guids = list(dict.fromkeys(i["element_guid"] for i in items))
    rows = await _gdl_rows(
        client, receipt["target"]["port"], guids, receipt["write_timeout_seconds"]
    )
    for item in items:
        requested = item["parameters"]["gdlParameters"][0]
        row = rows[item["element_guid"]]
        parameters = row.get("parameters", []) if isinstance(row, dict) else []
        matches = [p for p in parameters if p.get("name") == requested["name"]]
        actual = matches[0] if len(matches) == 1 else {}
        item["after"] = actual
        differences = write._mismatches(
            {"type": item["expected_type"], "value": requested["value"]}, actual
        )
        if isinstance(requested["value"], bool) and actual.get("value") is not requested["value"]:
            differences.append("value.type")
        item["status"] = "verification_failed" if differences else "verified"
        if differences:
            item["mismatches"] = differences


async def _gdl_dispatch(client, receipt):
    await _execute(
        client, receipt, "SetGDLParametersOfElements", "elementsWithGDLParameters", _verify_gdl
    )


async def set_gdl_parameters(
    client: ArchicadClient,
    changes: list[dict | GDLChange],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 100 existing scalar Object parameters, by element/name/value.

    Metres/radians. Refuses fixed/hidden/locked/disabled/array parameters, hotlinks and
    locked elements. Shared token, explicit port and per-change receipts; never saves.
    """
    if not 1 <= len(changes) <= 100:
        raise ValueError("Pass between 1 and 100 GDL changes.")
    validated = [c if isinstance(c, GDLChange) else GDLChange.model_validate(c) for c in changes]
    pairs = [(c.element_guid, c.name) for c in validated]
    if len(set(pairs)) != len(pairs):
        raise ValueError("Each element/parameter pair may appear once.")
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "set_gdl_parameters",
        planner_override=_gdl_plan,
        dispatcher_override=_gdl_dispatch,
    )


class WallModify(write.InputModel):
    guid: str
    height: write.Positive | None = None
    thickness: write.Positive | None = None
    bottomOffset: float | None = None
    begCoordinate: write.Point | None = None
    endCoordinate: write.Point | None = None

    @field_validator("guid")
    @classmethod
    def canonical_guid(cls, value):
        return str(UUID(value)).upper()

    @model_validator(mode="after")
    def has_changes(self):
        if not self.model_dump(exclude={"guid"}, exclude_none=True):
            raise ValueError("Supply at least one wall field to modify.")
        return self


async def _wall_plan(client, walls, port, operation):
    port, target, rows = await _editable(client, [wall.guid for wall in walls], port)
    items = []
    for index, (wall, row) in enumerate(zip(walls, rows, strict=True)):
        details = row.get("details")
        if row["type"] != "Wall" or not isinstance(details, dict):
            raise ValueError("Only walls with readable geometry are supported.")
        arc = details.get("arcAngle")
        if (
            details.get("geometryType") != "Straight"
            or not isinstance(arc, (int, float))
            or (isinstance(arc, bool) or not math.isfinite(arc) or abs(arc) > 1e-9)
            or details.get("profileType") in {"Trapez", "Poly"}
        ):
            raise ValueError("Curved, trapezoidal or polygonal walls are refused.")
        changes = wall.model_dump(exclude={"guid"}, exclude_none=True)
        if "thickness" in changes and details.get("structureType") != "Basic":
            raise ValueError("Direct thickness changes require a Basic wall.")
        start = changes.get("begCoordinate", details.get("begCoordinate"))
        end = changes.get("endCoordinate", details.get("endCoordinate"))
        if not isinstance(start, dict) or not isinstance(end, dict):
            raise ValueError("Wall endpoints are required for safe editing.")
        start = write.Point.model_validate(start).model_dump()
        end = write.Point.model_validate(end).model_dump()
        if math.hypot(start["x"] - end["x"], start["y"] - end["y"]) < 1e-6:
            raise ValueError("The resulting wall would have zero length.")
        expected = {"geometryType": "Straight", "arcAngle": 0.0}
        for key, value in changes.items():
            native = "begThickness" if key == "thickness" else key
            if native not in details:
                raise ValueError(f"Cannot read existing wall field {native}.")
            expected[native] = value
        if "height" in changes:
            expected["relativeTopStory"] = 0.0  # Native ModifyWalls unlinks height.
        if "bottomOffset" in changes:
            floor = next(s for s in target["stories"] if s["index"] == row["floorIndex"])
            expected["zCoordinate"] = floor["level"] + changes["bottomOffset"]
        items.append(
            {
                "index": index,
                "status": "ready",
                "element_guid": wall.guid,
                "floorIndex": row.get("floorIndex"),
                "layerIndex": row.get("layerIndex"),
                "before": deepcopy(row),
                "new": changes,
                "expected": expected,
                "parameters": {"elementId": {"guid": wall.guid}, **changes},
            }
        )
    return {"operation": operation, "target": target, "items": items}


async def _verify_walls(client, receipt, items):
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
        raise ValueError("Unexpected modified-wall response cardinality.")
    for item, row in zip(items, rows, strict=True):
        item["after"] = row
        differences = write._mismatches(
            {
                "type": "Wall",
                "floorIndex": item["floorIndex"],
                "layerIndex": item["layerIndex"],
                "details": item["expected"],
            },
            row,
        )
        item["status"] = "verification_failed" if differences else "verified"
        if differences:
            item["mismatches"] = differences


async def _wall_dispatch(client, receipt):
    await _execute(client, receipt, "ModifyWalls", "wallsWithDetails", _verify_walls)


async def modify_walls(
    client: ArchicadClient,
    walls: list[dict | WallModify],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/modify up to 50 straight walls. Fields are native camelCase; metres.

    Only height/thickness/bottomOffset/begCoordinate/endCoordinate. Direct thickness
    requires Basic structure; changing height unlinks the top story, as Tapir does.
    Refuses curved/trapezoidal, hotlinked, locked/nonexistent walls. Per-wall receipts
    and read-back verification with shared token/explicit-port/timeout; never saves.
    """
    validated = [w if isinstance(w, WallModify) else WallModify.model_validate(w) for w in walls]
    _unique([w.guid for w in validated], 50)
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "modify_walls",
        planner_override=_wall_plan,
        dispatcher_override=_wall_dispatch,
    )
