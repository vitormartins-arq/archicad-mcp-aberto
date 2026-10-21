"""Associative wall dimensions, through Tapir 1.7.0.

``CreateWallThicknessDimensions`` dimensions both faces of an existing wall on the
wall's own story; the dimension stays linked to the wall. The dimension line passes
through ``reference_point`` along ``direction`` (both plan metres). By default the point
is the middle of the wall's reference line and the direction is perpendicular to it, so
the dimension crosses the wall. Display settings come from the Dimension tool defaults.

``CreateAssociativeDimensions`` dimensions between end points of existing straight walls
(``inIndex`` 1 and 2 are the two ends of the wall's reference line, per Tapir's own
example). The dimension stays linked to the walls; it is read back with
``GetDimensionData``, witness point by witness point.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import edit, read, write

MAX_DIMENSIONS = 50


class Point2D(write.InputModel):
    x: float
    y: float


class WallThicknessDimension(write.InputModel):
    wall_guid: str
    reference_point: Point2D | None = None
    direction: Point2D | None = None

    @field_validator("wall_guid")
    @classmethod
    def canonical_guid(cls, value):
        return str(UUID(value)).upper()


def _coordinate(details: dict, key: str, label: str) -> tuple[float, float]:
    point = details.get(key)
    if not isinstance(point, dict):
        raise ValueError(f"{label}: cannot read the wall {key}.")
    x, y = point.get("x"), point.get("y")
    if not all(isinstance(v, int | float) and math.isfinite(v) for v in (x, y)):
        raise ValueError(f"{label}: cannot read the wall {key}.")
    return float(x), float(y)


def _line(dimension: WallThicknessDimension, row: dict, label: str) -> tuple[dict, dict]:
    if dimension.reference_point and dimension.direction:
        point, direction = dimension.reference_point, dimension.direction
        if not all(math.isfinite(v) for v in (point.x, point.y, direction.x, direction.y)):
            raise ValueError(f"{label}: reference point and direction must be finite.")
        if direction.x == 0 and direction.y == 0:
            raise ValueError(f"{label}: the direction must be non-zero.")
        return point.model_dump(), direction.model_dump()
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    straight = details.get("geometryType", "Straight") == "Straight" and not details.get("arcAngle")
    (x1, y1), (x2, y2) = (
        _coordinate(details, "begCoordinate", label),
        _coordinate(details, "endCoordinate", label),
    )
    if dimension.direction is None and not straight:
        raise ValueError(f"{label}: give a direction for a curved wall.")
    if dimension.direction is None and (x1, y1) == (x2, y2):
        raise ValueError(f"{label}: the wall has no length, so give a direction.")
    point = (
        dimension.reference_point.model_dump()
        if dimension.reference_point
        else {"x": (x1 + x2) / 2, "y": (y1 + y2) / 2}
    )
    if dimension.direction is not None:
        direction = dimension.direction.model_dump()
        if direction["x"] == 0 and direction["y"] == 0:
            raise ValueError(f"{label}: the direction must be non-zero.")
    else:
        length = math.hypot(x2 - x1, y2 - y1)
        # + 0.0 turns -0.0 into 0.0 for a readable preview.
        direction = {"x": -(y2 - y1) / length + 0.0, "y": (x2 - x1) / length + 0.0}
    if not all(math.isfinite(v) for v in (*point.values(), *direction.values())):
        raise ValueError(f"{label}: reference point and direction must be finite.")
    return point, direction


async def _plan(client, dimensions, port, operation):
    guids = [d.wall_guid for d in dimensions]
    port, target, rows = await edit._editable(client, guids, port)
    items = []
    for i, (dimension, row) in enumerate(zip(dimensions, rows, strict=True)):
        label = f"Dimension {i}"
        if row.get("type") != "Wall":
            raise ValueError(f"{label}: element {dimension.wall_guid} is not a wall.")
        point, direction = _line(dimension, row, label)
        items.append(
            {
                "index": i,
                "status": "ready",
                "wall_guid": dimension.wall_guid,
                "floorIndex": row.get("floorIndex"),
                "parameters": {
                    "wallId": {"guid": dimension.wall_guid},
                    "referencePoint": point,
                    "direction": direction,
                },
            }
        )
    return {"operation": operation, "target": target, "items": items}


def _mismatches(item: dict, row) -> list[str]:
    # Tapir reports no dimension-specific details, so type and story are what can be read.
    return write._mismatches({"type": "Dimension", "floorIndex": item["floorIndex"]}, row)


async def _dispatch(client, receipt):
    await write._dispatch(client, receipt, _mismatches)


async def create_wall_thickness_dimensions(
    client: ArchicadClient,
    dimensions: list[dict | WallThicknessDimension],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/create up to 50 associative thickness dimensions on existing editable walls,
    one per wall, on the wall's story. Optional reference_point and direction in plan metres;
    by default the line crosses the wall's middle, perpendicular to it. Dimension defaults
    for display. Reads back type and story; never saves.
    """
    entries = [
        d if isinstance(d, WallThicknessDimension) else WallThicknessDimension.model_validate(d)
        for d in dimensions
    ]
    edit._unique([d.wall_guid for d in entries], MAX_DIMENSIONS)
    return await write._write(
        client,
        entries,
        port,
        dry_run,
        confirmation_token,
        "create_wall_thickness_dimensions",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )


TOLERANCE = 0.001  # metres, for the witness points read back
WALL_ENDS = {"start": ("begCoordinate", 1), "end": ("endCoordinate", 2)}


class WallEnd(write.InputModel):
    wall_guid: str
    end: Literal["start", "end"]

    @field_validator("wall_guid")
    @classmethod
    def canonical_guid(cls, value):
        return str(UUID(value)).upper()


class WallPointsDimension(write.InputModel):
    points: Annotated[list[WallEnd], Field(min_length=2, max_length=20)]
    reference_point: Point2D
    direction: Point2D | None = None


async def _points_plan(client, dimensions, port, operation):
    guids = list(dict.fromkeys(p.wall_guid for d in dimensions for p in d.points))
    port, target, rows = await edit._editable(client, guids, port)
    walls = dict(zip(guids, rows, strict=True))
    items = []
    for i, dimension in enumerate(dimensions):
        label = f"Dimension {i}"
        if len({(p.wall_guid, p.end) for p in dimension.points}) != len(dimension.points):
            raise ValueError(f"{label}: a wall end is repeated.")
        witnesses, floors = [], set()
        for point in dimension.points:
            row = walls[point.wall_guid]
            if row.get("type") != "Wall":
                raise ValueError(f"{label}: element {point.wall_guid} is not a wall.")
            details = row.get("details") if isinstance(row.get("details"), dict) else {}
            if details.get("geometryType", "Straight") != "Straight" or details.get("arcAngle"):
                raise ValueError(f"{label}: wall {point.wall_guid} is curved.")
            key, in_index = WALL_ENDS[point.end]
            x, y = _coordinate(details, key, label)
            floors.add(row.get("floorIndex"))
            witnesses.append(
                {
                    "wall_guid": point.wall_guid,
                    "end": point.end,
                    "inIndex": in_index,
                    "x": x,
                    "y": y,
                }
            )
        if len(floors) != 1:
            raise ValueError(f"{label}: all walls must be on the same story.")
        if dimension.direction is not None:
            direction = dimension.direction.model_dump()
        else:
            first = walls[dimension.points[0].wall_guid]["details"]
            (x1, y1), (x2, y2) = (
                _coordinate(first, "begCoordinate", label),
                _coordinate(first, "endCoordinate", label),
            )
            length = math.hypot(x2 - x1, y2 - y1)
            if length == 0:
                raise ValueError(f"{label}: the first wall has no length, so give a direction.")
            direction = {"x": (x2 - x1) / length + 0.0, "y": (y2 - y1) / length + 0.0}
        point = dimension.reference_point.model_dump()
        if not all(math.isfinite(v) for v in (*point.values(), *direction.values())):
            raise ValueError(f"{label}: reference point and direction must be finite.")
        if direction["x"] == 0 and direction["y"] == 0:
            raise ValueError(f"{label}: the direction must be non-zero.")
        floor = floors.pop()
        items.append(
            {
                "index": i,
                "status": "ready",
                "floorIndex": floor,
                "witnesses": witnesses,
                "parameters": {
                    "referencePoint": point,
                    "direction": direction,
                    "floorIndex": floor,
                    "witnessPoints": [
                        {"elementId": {"guid": w["wall_guid"]}, "inIndex": w["inIndex"]}
                        for w in witnesses
                    ],
                },
            }
        )
    return {"operation": operation, "target": target, "items": items}


def _witness_mismatches(item: dict, data) -> list[str]:
    points = data.get("witnessPoints") if isinstance(data, dict) else None
    if not isinstance(points, list) or len(points) != len(item["witnesses"]):
        return ["witnessPoints"]
    differences = []
    for n, (wanted, found) in enumerate(zip(item["witnesses"], points, strict=True)):
        base = found.get("baseElementId") if isinstance(found, dict) else None
        guid = base.get("guid") if isinstance(base, dict) else None
        if not isinstance(guid, str) or guid.upper() != wanted["wall_guid"]:
            differences.append(f"witnessPoints.{n}.baseElementId")
        at = found.get("coordinate") if isinstance(found, dict) else None
        if not isinstance(at, dict) or not all(
            isinstance(at.get(k), int | float) and abs(at[k] - wanted[k]) <= TOLERANCE for k in "xy"
        ):
            differences.append(f"witnessPoints.{n}.coordinate")
    return differences


async def _points_dispatch(client, receipt):
    await write._dispatch(client, receipt, _mismatches)
    checked = [i for i in receipt["items"] if i["status"] == "verified"]
    if not checked:
        return
    try:
        raw = await client.tapir(
            receipt["target"]["port"],
            "GetDimensionData",
            {"elements": read.element_ids([i["element_guid"] for i in checked])},
            timeout=receipt["write_timeout_seconds"],
        )
        rows = raw.get("dimensionsData")
        if not isinstance(rows, list) or len(rows) != len(checked):
            raise ValueError("Unexpected dimension data response cardinality.")
    except (ArchicadError, ValueError) as exc:
        for item in checked:
            item.update(status="unverified", error=f"Dimension data not read: {exc}")
        return
    for item, data in zip(checked, rows, strict=True):
        item["dimension_data"] = data
        differences = _witness_mismatches(item, data)
        if differences:
            item["status"] = "verification_failed"
            item["mismatches"] = item.get("mismatches", []) + differences


async def create_associative_dimensions(
    client: ArchicadClient,
    dimensions: list[dict | WallPointsDimension],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/create up to 50 linear dimensions between end points of existing straight
    walls (2 to 20 points, all on one story), linked to the walls. The dimension line
    passes through reference_point; direction defaults to the first wall's direction.
    Reads back type, story and each witness point; never saves.
    """
    entries = [
        d if isinstance(d, WallPointsDimension) else WallPointsDimension.model_validate(d)
        for d in dimensions
    ]
    if not 1 <= len(entries) <= MAX_DIMENSIONS:
        raise ValueError(f"Pass between 1 and {MAX_DIMENSIONS} dimensions.")
    return await write._write(
        client,
        entries,
        port,
        dry_run,
        confirmation_token,
        "create_associative_dimensions",
        planner_override=_points_plan,
        dispatcher_override=_points_dispatch,
    )
