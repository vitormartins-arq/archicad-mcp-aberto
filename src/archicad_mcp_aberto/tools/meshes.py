"""Simple 3D terrains and limited mesh edits, through Tapir 1.7.0.

Public outline.z and level are absolute project metres. Tapir mesh.level is relative
to its story, while meshPolyZ vertex heights are relative to that base plane.
No holes, arcs or internal contour lines are created in this initial tool.
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import edit, modify, write

MAX_MESHES = 20
SkirtType = Literal["SurfaceOnlyWithoutSkirt", "WithSkirt", "SolidBodyWithSkirt"]
Ridges = Literal["AllSharp", "AllSmooth", "UserDefined"]
Depth = Annotated[float, Field(ge=0)]


class Point3D(write.InputModel):
    x: float
    y: float
    z: float


class MeshCreate(write.InputModel):
    outline: Annotated[list[Point3D], Field(min_length=3, max_length=200)]
    floor_index: int
    level: float
    skirt_type: SkirtType = "SurfaceOnlyWithoutSkirt"
    skirt_depth: Depth = 1.0
    ridges: Ridges = "AllSharp"
    show_lines: bool = True

    @model_validator(mode="after")
    def simple_outline(self):
        points = self.outline
        if (points[0].x, points[0].y) == (points[-1].x, points[-1].y):
            if points[0].z != points[-1].z:
                raise ValueError("A repeated closing mesh vertex must have the same Z.")
            points = points[:-1]
        write.SlabCreate(
            outline=[{"x": p.x, "y": p.y} for p in points],
            floor_index=self.floor_index,
            thickness=1.0,
            level=0.0,
        )
        _skirt(self.skirt_type, self.skirt_depth, [p.z - self.level for p in points])
        self.outline = points
        return self


class MeshModify(modify._Edit):
    level: float | None = None
    skirt_type: SkirtType | None = None
    skirt_depth: Depth | None = None
    ridges: Ridges | None = None
    show_lines: bool | None = None


def _skirt(kind, depth, heights):
    if kind not in ("SurfaceOnlyWithoutSkirt", "WithSkirt", "SolidBodyWithSkirt"):
        raise ValueError("Cannot read the mesh skirt type.")
    if not all(math.isfinite(h) for h in heights):
        raise ValueError("Mesh heights relative to the base plane must be finite.")
    if kind != "SurfaceOnlyWithoutSkirt" and (depth <= 0 or min(heights) <= -depth):
        raise ValueError("The mesh skirt bottom must be strictly below every boundary vertex.")


def _payload(mesh, story):
    level = mesh.level - story["level"]
    if not math.isfinite(level):
        raise ValueError("Mesh base offset must be finite.")
    return {
        "floorIndex": mesh.floor_index,
        "level": level,
        "skirtType": mesh.skirt_type,
        "skirtLevel": mesh.skirt_depth,
        "ridges": mesh.ridges,
        "showLines": mesh.show_lines,
        "polygonCoordinates": [{"x": p.x, "y": p.y, "z": p.z - mesh.level} for p in mesh.outline],
        "polygonArcs": [],
        "holes": [],
    }


async def _create_plan(client, meshes, port, operation):
    port, target, floors = await write._context(client, port)
    items = []
    for i, mesh in enumerate(meshes):
        if mesh.floor_index not in floors:
            raise ValueError(f"Mesh {i}: story {mesh.floor_index} does not exist.")
        story = next(s for s in target["stories"] if s["index"] == mesh.floor_index)
        items.append(
            {
                "index": i,
                "status": "ready",
                "floorIndex": mesh.floor_index,
                "base_plane_level": mesh.level,
                "outline_absolute": [p.model_dump() for p in mesh.outline],
                "parameters": _payload(mesh, story),
            }
        )
    return {"operation": operation, "target": target, "items": items}


def _mismatches(item: dict, row: Any) -> list[str]:
    p = item["parameters"]
    differences = write._mismatches(
        {
            "type": "Mesh",
            "floorIndex": p["floorIndex"],
            "details": {
                k: p[k] for k in ("level", "skirtType", "skirtLevel", "ridges", "showLines")
            },
        },
        row,
    )
    details = row.get("details") if isinstance(row, dict) else None
    details = details if isinstance(details, dict) else {}
    if not write._same_polygon(p["polygonCoordinates"], details.get("polygonCoordinates")):
        differences.append("details.polygonCoordinates")
    for key in ("polygonArcs", "holes", "sublines"):
        if details.get(key, []) != []:
            differences.append(f"details.{key}")
    return differences


async def _create_dispatch(client, receipt):
    await write._dispatch(client, receipt, _mismatches)


async def create_meshes(
    client: ArchicadClient,
    meshes: list[dict | MeshCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/create up to 20 simple terrains, 3–200 vertices; x/y/z and level in
    absolute project metres. Default is a surface without a skirt. No holes/arcs/contours.
    Layer/material inherit Mesh defaults. Reads back geometry and fields; never saves.
    """
    if not 1 <= len(meshes) <= MAX_MESHES:
        raise ValueError(f"Pass between 1 and {MAX_MESHES} meshes.")
    entries = [m if isinstance(m, MeshCreate) else MeshCreate.model_validate(m) for m in meshes]
    return await write._write(
        client,
        entries,
        port,
        dry_run,
        confirmation_token,
        "create_meshes",
        planner_override=_create_plan,
        dispatcher_override=_create_dispatch,
    )


async def _modify_plan(client, meshes, port, operation):
    port, target, rows = await edit._editable(client, [m.guid for m in meshes], port)
    items = []
    for i, (mesh, row) in enumerate(zip(meshes, rows, strict=True)):
        details = row.get("details")
        if row.get("type") != "Mesh" or not isinstance(details, dict):
            raise ValueError(f"Element {mesh.guid} is not a Mesh with details.")
        if any(details.get(k, []) != [] for k in ("polygonArcs", "holes", "sublines")):
            raise ValueError(
                "Initial mesh edits support simple meshes only: no holes, arcs or contours."
            )
        changes = mesh.model_dump(exclude={"guid"}, exclude_none=True)
        native = {}
        for public, key in (
            ("level", "level"),
            ("skirt_type", "skirtType"),
            ("skirt_depth", "skirtLevel"),
            ("ridges", "ridges"),
            ("show_lines", "showLines"),
        ):
            if public in changes:
                if key not in details:
                    raise ValueError(f"Mesh {i}: cannot read current {key}.")
                native[key] = changes[public]
        if "level" in native:
            story = modify._story(target, row)
            native["level"] -= story["level"]
            if not math.isfinite(native["level"]):
                raise ValueError("Mesh base offset must be finite.")
        points = details.get("polygonCoordinates")
        if not isinstance(points, list) or len(points) < 3:
            raise ValueError("Cannot read mesh boundary vertex heights.")
        heights = [modify._number(p, "z", f"Mesh {i}") for p in points if isinstance(p, dict)]
        if len(heights) != len(points):
            raise ValueError("Cannot read mesh boundary vertex heights.")
        _skirt(
            native.get("skirtType", details.get("skirtType")),
            native.get("skirtLevel", modify._number(details, "skirtLevel", f"Mesh {i}")),
            heights,
        )
        # Geometry is not replaced by these edits; require it unchanged in the read-back.
        expected = {
            **native,
            **{
                k: deepcopy(details[k])
                for k in ("polygonCoordinates", "polygonArcs", "holes", "sublines")
                if k in details
            },
        }
        items.append(
            {
                "index": i,
                "status": "ready",
                "element_guid": mesh.guid,
                "type": "Mesh",
                "floorIndex": row["floorIndex"],
                "layerIndex": row.get("layerIndex"),
                "before": deepcopy(row),
                "new": changes,
                "expected": expected,
                "parameters": {"elementId": {"guid": mesh.guid}, "meshData": native},
            }
        )
    return {"operation": operation, "target": target, "items": items}


async def _modify_dispatch(client, receipt):
    await edit._execute(client, receipt, "ModifyMeshes", "meshesData", modify._verify)


async def modify_meshes(
    client: ArchicadClient,
    meshes: list[dict | MeshModify],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/edit up to 20 simple existing terrains: absolute base level, skirt type/depth,
    ridges, show_lines. Level moves the whole surface; boundary/topology/owner story
    are preserved. No vertex, holes or internal contour edits; never saves.
    """
    entries = [m if isinstance(m, MeshModify) else MeshModify.model_validate(m) for m in meshes]
    edit._unique([m.guid for m in entries], MAX_MESHES)
    return await write._write(
        client,
        entries,
        port,
        dry_run,
        confirmation_token,
        "modify_meshes",
        planner_override=_modify_plan,
        dispatcher_override=_modify_dispatch,
    )
