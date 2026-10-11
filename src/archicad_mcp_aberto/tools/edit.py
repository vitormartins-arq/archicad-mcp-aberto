"""Safe edits of existing elements; SI units, shared confirmation and receipts."""

from __future__ import annotations

import math
from copy import deepcopy
from uuid import UUID

from pydantic import field_validator

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
                elif abs(math.remainder(found - wanted, math.tau)) > 1e-7:
                    differences.append(key)
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
