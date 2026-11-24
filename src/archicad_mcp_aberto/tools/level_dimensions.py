"""Native associative level dimensions from exact favorites. Metres; never saves."""

from __future__ import annotations

import math
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadError, resolve_port
from archicad_mcp_aberto.tools import grids, write


class LevelDimensionCreate(write.InputModel):
    point: write.Point
    floor_index: Annotated[int, Field(ge=-32768, le=32767)]
    slab_guid: str
    favorite: Annotated[str, Field(min_length=1, max_length=255)]
    reference: Literal["favorite", "top", "bottom"] = "favorite"
    datum: Literal["favorite", "project_zero"] = "favorite"

    @field_validator("slab_guid")
    @classmethod
    def guid(cls, value):
        return str(UUID(value)).upper()


def payload(d):
    return {
        "point": d.point.model_dump(),
        "floorIndex": d.floor_index,
        "slabGuid": d.slab_guid,
        "favorite": d.favorite,
        "reference": d.reference,
        "datum": d.datum,
    }


async def get_level_dimensions(
    client, port=None, floor_index=None, guids=None, include_drawing=False
):
    """Read native association/style/value and optional drawn text without selection changes."""
    params = {"includeDrawing": include_drawing}
    if floor_index is not None:
        if type(floor_index) is not int or not -32768 <= floor_index <= 32767:
            raise ValueError("Invalid story index.")
        params["floorIndex"] = floor_index
    if guids is not None:
        if not 1 <= len(guids) <= 100:
            raise ValueError("Pass 1..100 explicit dimension GUIDs.")
        params["guids"] = [str(UUID(g)).upper() for g in guids]
    port = await resolve_port(client, port)
    result = await grids._addon(client, port, "GetLevelDimensions", params)
    if not isinstance(result.get("dimensions"), list):
        raise ValueError("Invalid native level-dimension response.")
    return {"port": port, **result}


async def _plan(client, dimensions, port, operation):
    port = await resolve_port(client, port)
    native = await grids._addon(
        client, port, "PlanLevelDimensions", {"dimensions": [payload(d) for d in dimensions]}
    )
    rows = native.get("items")
    if (
        not isinstance(rows, list)
        or len(rows) != len(dimensions)
        or not isinstance(native.get("context"), dict)
    ):
        raise ValueError("Incomplete native plan; nothing inferred.")
    items = []
    for i, (d, row) in enumerate(zip(dimensions, rows, strict=True)):
        for key in ("topElevationProject", "bottomElevationProject", "measuredLevel"):
            if type(row.get(key)) not in (int, float) or not math.isfinite(row[key]):
                raise ValueError("Native slab elevations missing/nonfinite.")
        if (
            row.get("type") != "LevelDimension"
            or row.get("static") is not False
            or row.get("parentGuid", "").upper() != d.slab_guid
        ):
            raise ValueError("Native plan lost associative slab reference.")
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
        "target": {"port": port, "project": native["context"]},
        "native_plan": native,
        "items": items,
    }


def mismatches(expected, actual):
    problems = []
    for key in (
        "type",
        "floorIndex",
        "parentType",
        "parentGuid",
        "static",
        "layerIndex",
        "pen",
        "symbol",
        "markerSize",
        "angle",
        "needPlus",
        "origin",
        "hideWithBaseElement",
        "note1",
        "note2",
        "point",
        "measuredLevel",
    ):
        wanted, found = expected.get(key), actual.get(key)
        if isinstance(wanted, (int, float)) and not isinstance(wanted, bool):
            same = (
                type(found) in (int, float) and math.isfinite(found) and abs(found - wanted) <= 1e-6
            )
        else:
            same = wanted == found
        if not same:
            problems.append(key)
    if actual.get("drawingError") != 0 or not actual.get("drawnTexts"):
        problems.append("drawnTexts")
    return problems


async def _dispatch(client, receipt):
    port = receipt["target"]["port"]
    try:
        result = await grids._addon(
            client,
            port,
            "CreateLevelDimensions",
            {
                "dimensions": [i["parameters"] for i in receipt["items"]],
                "expectedPlan": receipt["native_plan"],
            },
            timeout=receipt["write_timeout_seconds"],
        )
    except (ArchicadError, ValueError) as exc:
        for item in receipt["items"]:
            item.update(status="unknown", error=str(exc))
            if isinstance(exc, ArchicadError) and exc.detail is not None:
                item["native_error"] = exc.detail
        return
    rows = result.get("dimensions", [])
    if not isinstance(rows, list) or len(rows) != len(receipt["items"]):
        for item in receipt["items"]:
            item.update(status="unknown", error="Unexpected native result count; do not retry.")
        return
    guids = []
    for item, row in zip(receipt["items"], rows, strict=True):
        ids = row.get("existingGuids", []) if row.get("status") == "existing" else [row.get("guid")]
        if len(ids) != 1:
            item.update(status="verification_failed", error="Ambiguous existing dimensions.")
            continue
        try:
            item["element_guid"] = str(UUID(ids[0])).upper()
        except (TypeError, ValueError, AttributeError):
            item.update(status="unknown", error="No valid native dimension GUID.")
            continue
        item["status"] = "unverified"
        guids.append(item["element_guid"])
    if not guids:
        return
    try:
        readback = await get_level_dimensions(client, port, guids=guids, include_drawing=True)
        by_guid = {str(r.get("guid", "")).upper(): r for r in readback["dimensions"]}
        for item in receipt["items"]:
            if item["status"] != "unverified":
                continue
            actual = by_guid.get(item["element_guid"], {})
            problems = mismatches(item["expected"], actual)
            item.update(status="verification_failed" if problems else "verified", readback=actual)
            item["verification_scope"] = (
                "Native type, slab association, measured numeric level, favorite style/content "
                "and drawing presence. Formatted custom-text numbers require "
                "live visual acceptance."
            )
            if problems:
                item["mismatches"] = problems
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)


async def create_level_dimensions(
    client, dimensions, port=None, dry_run=True, confirmation_token=None
):
    """Preview/apply 1..20 native associative dimensions in one Undo step."""
    if not 1 <= len(dimensions) <= 20:
        raise ValueError("Pass 1..20 level dimensions.")
    validated = [
        d if isinstance(d, LevelDimensionCreate) else LevelDimensionCreate.model_validate(d)
        for d in dimensions
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_level_dimensions",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
