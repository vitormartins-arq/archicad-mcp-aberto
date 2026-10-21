"""Simple box morphs, through Tapir 1.7.0 CreateMorphs.

Each morph is an axis-aligned box: a base corner in absolute project metres and a
positive size. Tapir places the box with its corner at ``basePoint`` (``tranmat`` stays
absolute) and the explicit ``floorIndex`` decides the owner story. Building material,
surface and display settings inherit the Morph tool defaults in this initial tool.

The box goes to Tapir as an explicit closed ``body`` with ``bodyType`` Solid, not as
``size``: live on AC30 build 3001 BRA with Tapir 1.7.0 (20/10/2026), ``size`` built a
Surface body with five faces and ``isClosed`` false, an open box instead of a solid.
"""

from __future__ import annotations

import math
from typing import Annotated

from pydantic import Field, model_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import write
from archicad_mcp_aberto.tools.read import element_ids

MAX_MORPHS = 50
TOLERANCE = 0.001  # metres, for the read-back origin and 3D bounding box
Size = Annotated[float, Field(gt=0, le=1000)]


class Point3D(write.InputModel):
    x: float
    y: float
    z: float


class MorphCreate(write.InputModel):
    base_point: Point3D
    size_x: Size
    size_y: Size
    size_z: Size
    floor_index: int

    @model_validator(mode="after")
    def finite(self):
        if not all(math.isfinite(v) for v in self.base_point.model_dump().values()):
            raise ValueError("Morph base point must be finite.")
        return self


# Corners of the box relative to basePoint, then each face wound anticlockwise seen from
# outside, so every face normal points out of the solid.
FACES = ([0, 3, 2, 1], [4, 5, 6, 7], [0, 1, 5, 4], [1, 2, 6, 5], [2, 3, 7, 6], [3, 0, 4, 7])


def _body(morph: MorphCreate) -> dict:
    x, y, z = morph.size_x, morph.size_y, morph.size_z
    corners = [(0, 0), (x, 0), (x, y), (0, y)]
    vertices = [{"x": cx, "y": cy, "z": cz} for cz in (0, z) for cx, cy in corners]
    return {
        "bodyType": "Solid",
        "vertices": vertices,
        "polygons": [{"vertexIds": face} for face in FACES],
    }


def _box(morph: MorphCreate) -> dict:
    b = morph.base_point
    return {
        "xMin": b.x,
        "yMin": b.y,
        "zMin": b.z,
        "xMax": b.x + morph.size_x,
        "yMax": b.y + morph.size_y,
        "zMax": b.z + morph.size_z,
    }


async def _plan(client, morphs, port, operation):
    port, target, floors = await write._context(client, port)
    items = []
    for i, morph in enumerate(morphs):
        if morph.floor_index not in floors:
            raise ValueError(f"Morph {i}: story {morph.floor_index} does not exist.")
        items.append(
            {
                "index": i,
                "status": "ready",
                "floorIndex": morph.floor_index,
                "expected_box": _box(morph),
                "parameters": {
                    "basePoint": morph.base_point.model_dump(),
                    "body": _body(morph),
                    "floorIndex": morph.floor_index,
                },
            }
        )
    return {"operation": operation, "target": target, "items": items}


def _close(a, b) -> bool:
    return (
        isinstance(a, int | float)
        and isinstance(b, int | float)
        and not isinstance(a, bool)
        and abs(a - b) <= TOLERANCE
    )


def _mismatches(item: dict, row) -> list[str]:
    differences = write._mismatches({"type": "Morph", "floorIndex": item["floorIndex"]}, row)
    details = row.get("details") if isinstance(row, dict) else None
    details = details if isinstance(details, dict) else {}
    origin = details.get("origin")
    base = item["parameters"]["basePoint"]
    if not isinstance(origin, dict) or not all(_close(origin.get(k), base[k]) for k in base):
        differences.append("details.origin")
    axes = {"xAxis": (1, 0, 0), "yAxis": (0, 1, 0), "zAxis": (0, 0, 1)}
    for key, unit in axes.items():
        axis = details.get(key)
        if not isinstance(axis, dict) or not all(
            _close(axis.get(c), v) for c, v in zip("xyz", unit, strict=True)
        ):
            differences.append(f"details.{key}")
    body = details.get("body") if isinstance(details.get("body"), dict) else {}
    if body.get("bodyType") != "Solid":
        differences.append("details.body.bodyType")
    if body.get("isClosed") is not True:
        differences.append("details.body.isClosed")
    polygons = body.get("polygons")
    if not isinstance(polygons, list) or len(polygons) != len(FACES):
        differences.append("details.body.polygons")
    return differences


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
        wanted = item["expected_box"]
        if not isinstance(box, dict) or not all(_close(box.get(k), v) for k, v in wanted.items()):
            item["status"] = "verification_failed"
            item.setdefault("mismatches", []).append("boundingBox3D")


async def create_morphs(
    client: ArchicadClient,
    morphs: list[dict | MorphCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/create up to 50 box morphs: base corner x/y/z in absolute project metres,
    positive size_x/size_y/size_z and an explicit floor_index. Material and display inherit
    Morph defaults. Reads back type, story, origin, axes and 3D box; never saves.
    """
    if not 1 <= len(morphs) <= MAX_MORPHS:
        raise ValueError(f"Pass between 1 and {MAX_MORPHS} morphs.")
    entries = [m if isinstance(m, MorphCreate) else MorphCreate.model_validate(m) for m in morphs]
    return await write._write(
        client,
        entries,
        port,
        dry_run,
        confirmation_token,
        "create_morphs",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
