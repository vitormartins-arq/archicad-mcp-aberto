"""2D drafting on a story: lines, polylines, splines, arcs, circles, fills and hotspots
(Tapir 1.7.0).

Coordinates in metres, angles in radians. Every element needs its story; layer and fill
are named as in Archicad, and the pen is a pen-table index. Omitted settings keep the
tool default. Splines are auto-smoothed: Archicad places the Bezier handles itself.
Polylines, splines and fills are checked by the coordinates in their details
(Get2DBoundingBoxes answers error 7203 for them in Archicad 30). Archicad stores a
circle as a full Arc (begAngle == endAngle), which counts as a circle. Never saves.
"""

from __future__ import annotations

import math
from typing import Annotated, Any

from pydantic import Field, model_validator

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import write

MAX_ITEMS = 50
Pen = Annotated[int, Field(ge=1, le=255)]
Name = Annotated[str, Field(min_length=1, max_length=255)]


class _Drawn(write._Favored):
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


class SplineCreate(_Drawn):
    points: Annotated[list[write.Point], Field(min_length=3, max_length=500)]
    closed: bool = False

    @model_validator(mode="after")
    def no_repeats(self) -> SplineCreate:
        pairs = zip(self.points, self.points[1:], strict=False)
        if any(math.hypot(a.x - b.x, a.y - b.y) < 1e-6 for a, b in pairs):
            raise ValueError("Consecutive spline points must differ.")
        first, last = self.points[0], self.points[-1]
        if math.hypot(first.x - last.x, first.y - last.y) < 1e-6:
            raise ValueError("Do not repeat the first spline point; set closed instead.")
        return self


class HotspotCreate(_Drawn):
    position: write.Point
    height: float | None = None

    @model_validator(mode="after")
    def finite_height(self) -> HotspotCreate:
        if self.height is not None and not math.isfinite(self.height):
            raise ValueError("Hotspot height must be finite.")
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


class FillCreate(write._Favored):
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
    "create_splines": ("Spline", SplineCreate),
    "create_arcs": ("Arc", ArcCreate),
    "create_circles": ("Circle", CircleCreate),
    "create_fills": ("Hatch", FillCreate),
    "create_hotspots": ("Hotspot", HotspotCreate),
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
    elif operation == "create_splines":
        p |= {"coordinates": [q.model_dump() for q in item.points], "closed": item.closed}
    elif operation in ("create_arcs", "create_circles"):
        p |= {"origin": item.center.model_dump(), "radius": item.radius}
        if operation == "create_arcs":
            p |= {"begAngle": item.start_angle, "endAngle": item.end_angle}
    elif operation == "create_hotspots":
        p["position"] = item.position.model_dump()
        if item.height is not None:
            p["height"] = item.height
    else:
        p |= {"coordinates": [q.model_dump() for q in item.outline], "arcs": []}
        if item.contour_pen is not None:
            p["contourPenIndex"] = item.contour_pen
    if item.favorite is not None:
        p["favoriteName"] = item.favorite
    if item.pen is not None:
        pens = {"create_fills": "fillPenIndex", "create_hotspots": "penIndex"}
        p[pens.get(operation, "linePenIndex")] = item.pen
    return p


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
        entry["parameters"] = payload
        planned.append(entry)
    await write._resolve_favorites(client, port, KINDS[operation][0], items, planned)
    return {"operation": operation, "target": target, "items": planned}


def _angle_off(found: Any, wanted: float) -> bool:
    return (
        not isinstance(found, (int, float))
        or isinstance(found, bool)
        or not math.isfinite(found)
        or abs(math.remainder(found - wanted, math.tau)) > 1e-7
    )


def _ring(points: Any) -> list[tuple[float, float]] | None:
    """Points as (x, y), without a closing repeat of the first; None if malformed."""
    if not isinstance(points, list):
        return None
    out = []
    for q in points:
        x, y = (q.get("x"), q.get("y")) if isinstance(q, dict) else (None, None)
        if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (x, y)):
            return None
        out.append((float(x), float(y)))
    if len(out) > 1 and math.dist(out[0], out[-1]) < 1e-6:
        out.pop()
    return out


def _same_points(found: Any, wanted: list[dict], cyclic: bool) -> bool:
    actual, expected = _ring(found), _ring(wanted)
    if actual is None or expected is None or len(actual) != len(expected):
        return False
    shifts = range(len(actual)) if cyclic else range(1)
    return any(
        all(math.dist(actual[(i + k) % len(actual)], e) <= 0.001 for i, e in enumerate(expected))
        for k in shifts
    )


def _checker(operation: str):
    kind = KINDS[operation][0]

    def check(item: dict, row: Any) -> list[str]:
        p = item["parameters"]
        actual = row.get("details") if isinstance(row, dict) else None
        actual = actual if isinstance(actual, dict) else {}
        stored = kind
        if kind == "Circle" and isinstance(row, dict) and row.get("type") == "Arc":
            # Archicad 30 reads a circle back as an Arc whose start and end angles match.
            end = actual.get("endAngle")
            if isinstance(end, (int, float)) and not _angle_off(actual.get("begAngle"), end):
                stored = "Arc"
        expected: dict[str, Any] = {"type": stored, "floorIndex": p["floorInd"]}
        if "layerIndex" in p:
            expected["layerIndex"] = p["layerIndex"]
        details: dict[str, Any] = {
            key: p[key]
            for key in (
                "begCoordinate",
                "endCoordinate",
                "origin",
                "radius",
                "closed",
                "position",
                "height",
                "penIndex",
                "linePenIndex",
                "fillPenIndex",
                "contourPenIndex",
            )
            if key in p
        }
        if details:
            expected["details"] = details
        differences = write._mismatches(expected, row)
        for key in ("begAngle", "endAngle"):
            if key in p and _angle_off(actual.get(key), p[key]):
                differences.append(f"details.{key}")
        if "coordinates" in p and not _same_points(
            actual.get("coordinates"), p["coordinates"], cyclic=kind == "Hatch"
        ):
            differences.append("details.coordinates")
        if "fillId" in p:
            found = actual.get("fillId")
            guid = found.get("guid") if isinstance(found, dict) else None
            if not isinstance(guid, str) or guid.upper() != p["fillId"]["guid"]:
                differences.append("details.fillId")
        return differences

    return check


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
        dispatcher_override=lambda client, receipt: write._dispatch(
            client, receipt, _checker(operation)
        ),
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


async def create_splines(
    client: ArchicadClient,
    splines: list[dict | SplineCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 50 auto-smoothed splines through 3 to 500 points; closed joins
    the last point back to the first without repeating it."""
    return await _create(client, splines, port, dry_run, confirmation_token, "create_splines")


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


async def create_hotspots(
    client: ArchicadClient,
    hotspots: list[dict | HotspotCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 50 2D hotspots: position, optional height (metres, the
    hotspot's z on its story)."""
    return await _create(client, hotspots, port, dry_run, confirmation_token, "create_hotspots")
