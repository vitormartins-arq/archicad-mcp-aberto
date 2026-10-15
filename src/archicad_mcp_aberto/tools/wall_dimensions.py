"""Associative wall thickness dimensions, through Tapir 1.7.0.

``CreateWallThicknessDimensions`` dimensions both faces of an existing wall on the
wall's own story; the dimension stays linked to the wall. The dimension line passes
through ``reference_point`` along ``direction`` (both plan metres). By default the point
is the middle of the wall's reference line and the direction is perpendicular to it, so
the dimension crosses the wall. Display settings come from the Dimension tool defaults.
"""

from __future__ import annotations

import math
from uuid import UUID

from pydantic import field_validator

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import edit, write

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
