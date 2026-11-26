"""Candidate native radial dimensions on slab polygon arcs. Metres; never saves."""

import math
from typing import Annotated
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import resolve_port
from archicad_mcp_aberto.tools import angle_dimensions, grids, write


class RadialDimensionCreate(write.InputModel):
    slab_guid: str
    floor_index: Annotated[int, Field(ge=-32768, le=32767)]
    arc_begin_index: Annotated[int, Field(ge=1)]
    end_point: write.Point
    favorite: Annotated[str, Field(min_length=1, max_length=255)]

    @field_validator("slab_guid")
    @classmethod
    def guid(cls, value):
        return str(UUID(value)).upper()


def payload(d):
    return {
        "slabGuid": d.slab_guid,
        "floorIndex": d.floor_index,
        "arcBeginIndex": d.arc_begin_index,
        "endPoint": d.end_point.model_dump(),
        "favorite": d.favorite,
    }


async def get_radial_dimensions(client, port=None, guids=None):
    port = await resolve_port(client, port)
    params = {}
    if guids is not None:
        if not 1 <= len(guids) <= 100:
            raise ValueError("Pass1..100 radial dimension GUIDs.")
        params["guids"] = [str(UUID(g)).upper() for g in guids]
    result = await grids._addon(client, port, "GetRadialDimensions", params)
    if not isinstance(result.get("dimensions"), list):
        raise ValueError("Invalid radial dimension response.")
    return {"port": port, **result}


async def _plan(client, dimensions, port, operation):
    port = await resolve_port(client, port)
    plan = await grids._addon(
        client, port, "PlanRadialDimensions", {"dimensions": [payload(d) for d in dimensions]}
    )
    rows = plan.get("items")
    if (
        not isinstance(rows, list)
        or len(rows) != len(dimensions)
        or not isinstance(plan.get("context"), dict)
    ):
        raise ValueError("Incomplete native radial plan.")
    items = []
    for i, (d, row) in enumerate(zip(dimensions, rows, strict=True)):
        ref, radius = row.get("reference", {}), row.get("radius")
        if (
            row.get("type") != "RadialDimension"
            or ref.get("elementGuid", "").upper() != d.slab_guid
            or ref.get("line") is not True
        ):
            raise ValueError("Native radial slab reference missing.")
        if (
            type(ref.get("nodeId")) is not int
            or ref["nodeId"] <= 0
            or type(radius) not in (int, float)
            or not math.isfinite(radius)
            or radius <= 0
        ):
            raise ValueError("Native radial edge ID/radius missing.")
        items.append(
            {
                "index": i,
                "status": "ready",
                "parameters": payload(d),
                "expected": row,
                "duplicate_guids": row.get("existingGuids", []),
            }
        )
    return {
        "operation": operation,
        "target": {"port": port, "project": plan["context"]},
        "native_plan": plan,
        "items": items,
    }


async def _dispatch(client, receipt):
    await angle_dimensions._dispatch_native(
        client, receipt, "CreateRadialDimensions", get_radial_dimensions
    )


async def create_radial_dimensions(
    client, dimensions, port=None, dry_run=True, confirmation_token=None
):
    if not 1 <= len(dimensions) <= 20:
        raise ValueError("Pass1..20 radial dimensions.")
    validated = [
        d if isinstance(d, RadialDimensionCreate) else RadialDimensionCreate.model_validate(d)
        for d in dimensions
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_radial_dimensions",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
