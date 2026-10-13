"""2D drafting on a story: lines, polylines, arcs, circles and fills (Tapir 1.7.0).

Coordinates in metres, angles in radians. Every element needs its story; layer and fill
are named as in Archicad, and the pen is a pen-table index. Omitted settings keep the
tool default. Polylines and fills carry no geometry in their details, so their plan box
is checked instead. Never saves.
"""

from __future__ import annotations

import math
from typing import Annotated, Any

from pydantic import Field, model_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import read, write

MAX_ITEMS = 50
Pen = Annotated[int, Field(ge=1, le=255)]
Name = Annotated[str, Field(min_length=1, max_length=255)]


class _Drawn(write.InputModel):
    floor_index: int
    layer: Name | None = None
    pen: Pen | None = None


class LineCreate(_Drawn):
    start: write.Point
    end: write.Point

    @model_validator(mode="after")
    def has_length(self) -> LineCreate:
        if math.hypot(self.start.x - self.end.x, self.start.y - self.end.y) < 1e-6:
            raise ValueError("A line must not have zero length.")
        return self


class PolylineCreate(_Drawn):
    points: Annotated[list[write.Point], Field(min_length=2, max_length=500)]

    @model_validator(mode="after")
    def no_repeats(self) -> PolylineCreate:
        pairs = zip(self.points, self.points[1:], strict=False)
        if any(math.hypot(a.x - b.x, a.y - b.y) < 1e-6 for a, b in pairs):
            raise ValueError("Consecutive polyline points must differ; repeat the first to close.")
        return self


class CircleCreate(_Drawn):
    center: write.Point
    radius: write.Positive


class ArcCreate(CircleCreate):
    start_angle: float
    end_angle: float

    @model_validator(mode="after")
    def has_sweep(self) -> ArcCreate:
        if abs(math.remainder(self.end_angle - self.start_angle, math.tau)) < 1e-9:
            raise ValueError("An arc needs different start and end angles; use a circle.")
        return self


class FillCreate(write.InputModel):
    outline: Annotated[list[write.Point], Field(min_length=3, max_length=200)]
    floor_index: int
    layer: Name | None = None
    fill: Name | None = None
    pen: Pen | None = None
    contour_pen: Pen | None = None

    @model_validator(mode="after")
    def simple_polygon(self) -> FillCreate:
        polygon = write.SlabCreate(
            outline=self.outline, floor_index=self.floor_index, thickness=1.0, level=0.0
        )
        self.outline = polygon.outline
        return self


# operation -> (element type, model)
KINDS = {
    "create_lines": ("Line", LineCreate),
    "create_polylines": ("PolyLine", PolylineCreate),
    "create_arcs": ("Arc", ArcCreate),
    "create_circles": ("Circle", CircleCreate),
    "create_fills": ("Hatch", FillCreate),
}


async def _attributes(client, port, kind: str) -> list[dict]:
    response = await client.tapir(port, "GetAttributesByType", {"attributeType": kind})
    rows = response.get("attributes")
    if not isinstance(rows, list):
        raise ValueError(f"Unexpected {kind} attribute response.")
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get("name"), str)]


def _named(rows: list[dict], wanted: str, noun: str) -> dict:
    found = [r for r in rows if r["name"].casefold() == wanted.strip().casefold()]
    if len(found) != 1:
        problem = "is ambiguous" if found else "does not exist"
        raise ValueError(f"{noun} {wanted!r} {problem} in this project.")
    return found[0]


def _payload(operation: str, item: Any) -> dict:
    p: dict[str, Any] = {"floorInd": item.floor_index}
    if operation == "create_lines":
        p |= {"begCoordinate": item.start.model_dump(), "endCoordinate": item.end.model_dump()}
    elif operation == "create_polylines":
        p |= {"coordinates": [q.model_dump() for q in item.points], "arcs": []}
    elif operation in ("create_arcs", "create_circles"):
        p |= {"origin": item.center.model_dump(), "radius": item.radius}
        if operation == "create_arcs":
            p |= {"begAngle": item.start_angle, "endAngle": item.end_angle}
    else:
        p |= {"coordinates": [q.model_dump() for q in item.outline], "arcs": []}
        if item.contour_pen is not None:
            p["contourPenIndex"] = item.contour_pen
    if item.pen is not None:
        p["fillPenIndex" if operation == "create_fills" else "linePenIndex"] = item.pen
    return p


def _box(points: list[dict]) -> dict:
    xs, ys = [q["x"] for q in points], [q["y"] for q in points]
    return {"xMin": min(xs), "yMin": min(ys), "xMax": max(xs), "yMax": max(ys)}


async def _plan(client, items, port, operation):
    port, target, floors = await write._context(client, port)
    layers = fills = None
    planned = []
    for index, item in enumerate(items):
        label = f"Item {index}"
        if item.floor_index not in floors:
            raise ValueError(f"{label}: story {item.floor_index} does not exist.")
        payload = _payload(operation, item)
        entry: dict[str, Any] = {"index": index, "status": "ready", "floorIndex": item.floor_index}
        try:
            if item.layer is not None:
                layers = layers if layers is not None else await _attributes(client, port, "Layer")
                layer = _named(layers, item.layer, "Layer")
                payload["layerIndex"] = entry["layerIndex"] = layer["index"]
            if getattr(item, "fill", None) is not None:
                fills = fills if fills is not None else await _attributes(client, port, "Fill")
                fill = _named(fills, item.fill, "Fill")
                payload["fillId"] = {"guid": str(fill["attributeId"]["guid"]).upper()}
                entry["fillName"] = fill["name"]
        except ValueError as exc:
            raise ValueError(f"{label}: {exc}") from None
        if "coordinates" in payload:
            entry["expected_box"] = _box(payload["coordinates"])
        entry["parameters"] = payload
        planned.append(entry)
    return {"operation": operation, "target": target, "items": planned}


def _angle_off(found: Any, wanted: float) -> bool:
    return (
        not isinstance(found, (int, float))
        or isinstance(found, bool)
        or not math.isfinite(found)
        or abs(math.remainder(found - wanted, math.tau)) > 1e-7
    )


def _checker(operation: str):
    kind = KINDS[operation][0]

    def check(item: dict, row: Any) -> list[str]:
        p = item["parameters"]
        expected: dict[str, Any] = {"type": kind, "floorIndex": p["floorInd"]}
        if "layerIndex" in p:
            expected["layerIndex"] = p["layerIndex"]
        details: dict[str, Any] = {}
        for key in (
            "begCoordinate",
            "endCoordinate",
            "origin",
            "radius",
            "linePenIndex",
            "fillPenIndex",
            "contourPenIndex",
        ):
            # PolyLine details carry neither geometry nor pen in Tapir 1.7.0.
            if key in p and kind != "PolyLine":
                details[key] = p[key]
        if details:
            expected["details"] = details
        differences = write._mismatches(expected, row)
        actual = row.get("details") if isinstance(row, dict) else None
        actual = actual if isinstance(actual, dict) else {}
        for key in ("begAngle", "endAngle"):
            if key in p and _angle_off(actual.get(key), p[key]):
                differences.append(f"details.{key}")
        if "fillId" in p:
            found = actual.get("fillId")
            guid = found.get("guid") if isinstance(found, dict) else None
            if not isinstance(guid, str) or guid.upper() != p["fillId"]["guid"]:
                differences.append("details.fillId")
        return differences

    return check


async def _check_boxes(client, receipt) -> None:
    items = [
        i
        for i in receipt["items"]
        if "expected_box" in i and i["status"] in ("verified", "verification_failed")
    ]
    if not items:
        return
    try:
        response = await client.command(
            receipt["target"]["port"],
            "Get2DBoundingBoxes",
            {"elements": read.element_ids([i["element_guid"] for i in items])},
            timeout=receipt["write_timeout_seconds"],
        )
        boxes = response.get("boundingBoxes2D")
        if not isinstance(boxes, list) or len(boxes) != len(items):
            raise ValueError("Unexpected box verification response.")
    except (ArchicadError, ValueError) as exc:
        for item in items:
            item["status"] = "unverified"
        receipt["verification_error"] = str(exc)
        return
    for item, box in zip(items, boxes, strict=True):
        item["after_box"] = box
        actual = box.get("boundingBox2D") if isinstance(box, dict) else None
        actual = actual if isinstance(actual, dict) else {}
        off = [
            f"box.{k}"
            for k, wanted in item["expected_box"].items()
            if not isinstance(actual.get(k), (int, float))
            or isinstance(actual.get(k), bool)
            or not math.isfinite(actual[k])
            or abs(actual[k] - wanted) > 0.001
        ]
        if off:
            item["status"] = "verification_failed"
            item["mismatches"] = item.get("mismatches", []) + off


def _dispatcher(operation: str):
    async def dispatch(client, receipt):
        await write._dispatch(client, receipt, _checker(operation))
        await _check_boxes(client, receipt)

    return dispatch


async def _create(client, items, port, dry_run, token, operation):
    model = KINDS[operation][1]
    if not 1 <= len(items) <= MAX_ITEMS:
        raise ValueError(f"Pass between 1 and {MAX_ITEMS} items.")
    validated = [i if isinstance(i, model) else model.model_validate(i) for i in items]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        token,
        operation,
        planner_override=_plan,
        dispatcher_override=_dispatcher(operation),
    )


async def create_lines(
    client: ArchicadClient,
    lines: list[dict | LineCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 50 straight 2D lines (start, end) on a story."""
    return await _create(client, lines, port, dry_run, confirmation_token, "create_lines")


async def create_polylines(
    client: ArchicadClient,
    polylines: list[dict | PolylineCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 50 straight-segment polylines; repeat the first point to close."""
    return await _create(client, polylines, port, dry_run, confirmation_token, "create_polylines")


async def create_arcs(
    client: ArchicadClient,
    arcs: list[dict | ArcCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 50 circular arcs: center, radius, start and end angle."""
    return await _create(client, arcs, port, dry_run, confirmation_token, "create_arcs")


async def create_circles(
    client: ArchicadClient,
    circles: list[dict | CircleCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 50 full circles: center and radius."""
    return await _create(client, circles, port, dry_run, confirmation_token, "create_circles")


async def create_fills(
    client: ArchicadClient,
    fills: list[dict | FillCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 50 fills (Archicad hatches) on simple polygons."""
    return await _create(client, fills, port, dry_run, confirmation_token, "create_fills")
