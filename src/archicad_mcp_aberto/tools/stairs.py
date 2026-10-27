"""Straight stairs, through Tapir 1.7.0 CreateStairs.

Each stair runs along a straight baseline from ``start`` to ``end`` in project metres,
from ``base_level`` (absolute project Z) on an explicit story. Total height, flight
width and number of risers are optional: left out, they come from the Stair tool
defaults or from ``favorite``. Archicad's stair rules decide riser and tread from them.

Tapir 1.7.0 returns no stair-specific details, so the read-back checks type and story,
then the 3D bounding box: it must cover the baseline in plan, start at the base level
and reach the total height when one was given. Never saves.
"""

from __future__ import annotations

import math
from typing import Annotated

from pydantic import Field, model_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import write
from archicad_mcp_aberto.tools.read import element_ids

MAX_STAIRS = 20
TOLERANCE = 0.01  # metres; finishes and nosings may stick out of the baseline a little
Length = Annotated[float, Field(gt=0, le=100)]


class StairCreate(write._Favored):
    start: write.Point
    end: write.Point
    floor_index: int
    base_level: float
    total_height: Length | None = None
    flight_width: Length | None = None
    risers: Annotated[int, Field(ge=2, le=200)] | None = None

    @model_validator(mode="after")
    def long_enough(self) -> StairCreate:
        if math.hypot(self.end.x - self.start.x, self.end.y - self.start.y) < 0.3:
            raise ValueError("A stair baseline must be at least 0.3 m long.")
        return self


def _payload(stair: StairCreate) -> dict:
    payload = {
        "baseLinePoints": [stair.start.model_dump(), stair.end.model_dump()],
        "zCoordinate": stair.base_level,
        "floorIndex": stair.floor_index,
    }
    for key, value in (
        ("totalHeight", stair.total_height),
        ("flightWidth", stair.flight_width),
        ("stepNum", stair.risers),
    ):
        if value is not None:
            payload[key] = value
    if stair.favorite is not None:
        payload["favoriteName"] = stair.favorite
    return payload


async def _plan(client, stairs, port, operation):
    port, target, floors = await write._context(client, port)
    exact = await write._favorite_names(client, port, "Stair", stairs)
    items = []
    for i, stair in enumerate(stairs):
        if stair.floor_index not in floors:
            raise ValueError(f"Stair {i}: story {stair.floor_index} does not exist.")
        item = {"index": i, "status": "ready", "parameters": _payload(stair)}
        if stair.favorite is not None:
            item["parameters"]["favoriteName"] = item["favorite"] = exact[stair.favorite]
        items.append(item)
    return {"operation": operation, "target": target, "items": items}


def _mismatches(item: dict, row) -> list[str]:
    p = item["parameters"]
    return write._mismatches({"type": "Stair", "floorIndex": p["floorIndex"]}, row)


def _box_mismatches(item: dict, box) -> list[str]:
    if not isinstance(box, dict) or not all(
        isinstance(box.get(k), int | float)
        for k in ("xMin", "xMax", "yMin", "yMax", "zMin", "zMax")
    ):
        return ["boundingBox3D"]
    p = item["parameters"]
    out = []
    for point in p["baseLinePoints"]:
        if not (
            box["xMin"] - TOLERANCE <= point["x"] <= box["xMax"] + TOLERANCE
            and box["yMin"] - TOLERANCE <= point["y"] <= box["yMax"] + TOLERANCE
        ):
            out.append("boundingBox3D.baseline")
            break
    if abs(box["zMin"] - p["zCoordinate"]) > TOLERANCE:
        out.append("boundingBox3D.zMin")
    height = p.get("totalHeight")
    if height is not None and box["zMax"] < p["zCoordinate"] + height - TOLERANCE:
        out.append("boundingBox3D.zMax")
    return out


async def _dispatch(client, receipt):
    await write._dispatch(client, receipt, _mismatches)
    checked = [i for i in receipt["items"] if i["status"] == "verified"]
    if not checked:
        return
    try:
        raw = await client.command(
            receipt["target"]["port"],
            "Get3DBoundingBoxes",
            {"elements": element_ids([i["element_guid"] for i in checked])},
        )
        rows = raw.get("boundingBoxes3D")
        if not isinstance(rows, list) or len(rows) != len(checked):
            raise ValueError("Unexpected bounding box response cardinality.")
    except (ArchicadError, ValueError) as exc:
        for item in checked:
            item.update(status="unverified", error=f"3D bounding box not read: {exc}")
        return
    for item, row in zip(checked, rows, strict=True):
        box = row.get("boundingBox3D") if isinstance(row, dict) else None
        item["after_box"] = box
        problems = _box_mismatches(item, box)
        if problems:
            item["status"] = "verification_failed"
            item.setdefault("mismatches", []).extend(problems)


async def create_stairs(
    client: ArchicadClient,
    stairs: list[dict | StairCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/create up to 20 straight stairs along a start-end baseline, from
    base_level (absolute Z) on floor_index. total_height, flight_width, risers and
    favorite are optional. Reads back type, story and 3D box; never saves.
    """
    if not 1 <= len(stairs) <= MAX_STAIRS:
        raise ValueError(f"Pass between 1 and {MAX_STAIRS} stairs.")
    entries = [s if isinstance(s, StairCreate) else StairCreate.model_validate(s) for s in stairs]
    return await write._write(
        client,
        entries,
        port,
        dry_run,
        confirmation_token,
        "create_stairs",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
