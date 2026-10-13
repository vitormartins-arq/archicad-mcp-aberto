"""Roofs from a plan polygon (Tapir CreateRoofs).

A single-plane roof slopes up from a pivot line by one angle. A multi-plane roof uses
the polygon as its pivot polygon and slopes up from every edge, by the tool default or
by the given levels. Lengths in metres, angles in radians; level is absolute project Z,
as in create_slabs. Never saves.
"""

from __future__ import annotations

import math
from typing import Annotated, Any

from pydantic import Field, model_validator

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import write

MAX_ROOFS = 20
Slope = Annotated[float, Field(gt=0, lt=math.pi / 2)]


class PivotLine(write.InputModel):
    start: write.Point
    end: write.Point


class RoofLevel(write.InputModel):
    height: float
    angle: Slope


class RoofCreate(write.InputModel):
    outline: Annotated[list[write.Point], Field(min_length=3, max_length=200)]
    floor_index: int
    level: float
    thickness: write.Positive
    pivot_line: PivotLine | None = None
    angle: Slope | None = None
    levels: Annotated[list[RoofLevel], Field(min_length=1, max_length=16)] | None = None
    eaves_overhang: Annotated[float, Field(ge=0)] | None = None

    @model_validator(mode="after")
    def valid_roof(self) -> RoofCreate:
        # Reuse the slab polygon validator, including closure normalization.
        polygon = write.SlabCreate(
            outline=self.outline, floor_index=self.floor_index, thickness=1.0, level=0.0
        )
        self.outline = polygon.outline
        if self.pivot_line is not None:
            if self.angle is None:
                raise ValueError("A single-plane roof (pivot_line) needs its slope angle.")
            if self.levels is not None or self.eaves_overhang is not None:
                raise ValueError("levels and eaves_overhang are only for multi-plane roofs.")
            a, b = self.pivot_line.start, self.pivot_line.end
            if math.hypot(a.x - b.x, a.y - b.y) < 1e-6:
                raise ValueError("The pivot line must not have zero length.")
        elif self.angle is not None:
            raise ValueError("angle is only for single-plane roofs; give pivot_line too.")
        heights = [level.height for level in self.levels or []]
        if heights != sorted(heights):
            raise ValueError("Roof levels must be ordered by non-decreasing height.")
        return self


def _payload(roof: RoofCreate) -> dict:
    payload: dict[str, Any] = {
        "floorIndex": roof.floor_index,
        "level": roof.level,
        "thickness": roof.thickness,
        "polygonCoordinates": [p.model_dump() for p in roof.outline],
        "polygonArcs": [],
        "holes": [],
    }
    if roof.pivot_line is not None:
        payload["pivotLine"] = {
            "begCoordinate": roof.pivot_line.start.model_dump(),
            "endCoordinate": roof.pivot_line.end.model_dump(),
        }
        payload["angle"] = roof.angle
    if roof.levels is not None:
        payload["levels"] = [
            {"levelHeight": level.height, "levelAngle": level.angle} for level in roof.levels
        ]
    if roof.eaves_overhang is not None:
        payload["eavesOverhang"] = roof.eaves_overhang
    return payload


async def _plan(client, roofs, port, operation):
    port, target, floors = await write._context(client, port)
    items = []
    for index, roof in enumerate(roofs):
        if roof.floor_index not in floors:
            raise ValueError(f"Roof {index}: story {roof.floor_index} does not exist.")
        items.append(
            {
                "index": index,
                "status": "ready",
                "roof_class": "SinglePlane" if roof.pivot_line else "MultiPlane",
                "parameters": _payload(roof),
            }
        )
    return {"operation": operation, "target": target, "items": items}


def _mismatches(target: dict):
    def check(item: dict, row: Any) -> list[str]:
        p = item["parameters"]
        story = next(s for s in target["stories"] if s["index"] == p["floorIndex"])
        details: dict[str, Any] = {
            "roofClass": item["roof_class"],
            "thickness": p["thickness"],
            "level": p["level"] - story["level"],
            "zCoordinate": p["level"],
        }
        if "pivotLine" in p:
            details["angle"] = p["angle"]
            details["pivotLine"] = {
                "begin": p["pivotLine"]["begCoordinate"],
                "end": p["pivotLine"]["endCoordinate"],
            }
        if "eavesOverhang" in p:
            details["eavesOverhang"] = p["eavesOverhang"]
        differences = write._mismatches(
            {"type": "Roof", "floorIndex": p["floorIndex"], "details": details}, row
        )
        actual = row.get("details") if isinstance(row, dict) else None
        actual = actual if isinstance(actual, dict) else {}
        if "levels" in p:
            wanted = [{"height": v["levelHeight"], "angle": v["levelAngle"]} for v in p["levels"]]
            found = actual.get("levels")
            if not isinstance(found, list) or len(found) != len(wanted):
                differences.append("details.levels")
            else:
                differences += [
                    f"details.levels.{i}.{key}"
                    for i, (a, b) in enumerate(zip(wanted, found, strict=True))
                    for key in write._mismatches(a, b)
                ]
        # A multi-plane roof's own contour grows by the overhang; its pivot polygon is ours.
        outline = "polygonOutline" if "pivotLine" in p else "pivotPolygonOutline"
        if not write._same_polygon(p["polygonCoordinates"], actual.get(outline)):
            differences.append(f"details.{outline}")
        return differences

    return check


async def _dispatch(client, receipt):
    await write._dispatch(client, receipt, _mismatches(receipt["target"]))


async def create_roofs(
    client: ArchicadClient,
    roofs: list[dict | RoofCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 roofs from simple polygons. Metres, radians, absolute level.

    With pivot_line and angle: one plane rising on the left of the line direction.
    Without: a multi-plane roof on the polygon, with optional levels and eaves_overhang.
    """
    if not 1 <= len(roofs) <= MAX_ROOFS:
        raise ValueError(f"Pass between 1 and {MAX_ROOFS} roofs.")
    validated = [r if isinstance(r, RoofCreate) else RoofCreate.model_validate(r) for r in roofs]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_roofs",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
