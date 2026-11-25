"""Native associative slab-top LevelDimensions through the companion add-on.

Contract: addon/Sources/LevelDimensionCommands.cpp in archicad-mcp-addon;
AC29/30 API_LevelDimensionType. Source-derived, not a live capture.
"""

from __future__ import annotations

import math
from typing import Annotated
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import AddOnError, ArchicadError, resolve_port
from archicad_mcp_aberto.tools import hotspot_dimensions, solids, write

_addon = hotspot_dimensions._addon


class LevelDimension(write.InputModel):
    slab_guid: str
    position: write.Point
    layer_index: Annotated[int, Field(ge=1, strict=True)] | None = None
    favorite: Annotated[str, Field(min_length=1)] | None = None

    @field_validator("slab_guid")
    @classmethod
    def guid(cls, value):
        return str(UUID(value)).upper()


def _rows(raw, count):
    rows = raw.get("elements")
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueError("Unexpected native LevelDimension response.")
    return rows


async def get_level_dimensions(client, element_guids, port=None):
    """Read 1..500 native level dimensions, values/owners/notes; metres, radians."""
    if not 1 <= len(element_guids) <= 500:
        raise ValueError("Pass 1 to 500 level dimension GUIDs.")
    guids = [str(UUID(g)).upper() for g in element_guids]
    port = await resolve_port(client, port)
    raw = await _addon(client, port, "GetLevelDimensions", {"guids": guids})
    return {"port": port, "elements": _rows(raw, len(guids))}


async def _plan(client, dimensions, port, operation):
    port, target, _ = await write._context(client, port)
    parameters = []
    for d in dimensions:
        p = {"slabGuid": d.slab_guid, "position": d.position.model_dump()}
        if d.layer_index is not None:
            p["layerIndex"] = d.layer_index
        if d.favorite is not None:
            p["favorite"] = d.favorite
        parameters.append(p)
    raw = await _addon(client, port, "PreviewLevelDimensions", {"dimensions": parameters})
    items = []
    for index, (p, row) in enumerate(zip(parameters, _rows(raw, len(parameters)), strict=True)):
        if not isinstance(row, dict) or "error" in row:
            items.append({"index": index, "status": "failed", "error": row})
            continue
        # Validate the contract before issuing a token; never offer a fake/static label.
        expected = {
            "slabGuid": p["slabGuid"],
            "position": p["position"],
            "staticLevel": False,
            "origin": 0,
        }
        if (
            write._mismatches(expected, row)
            or not isinstance(row.get("expectedLevel"), int | float)
            or isinstance(row.get("expectedLevel"), bool)
            or not math.isfinite(row["expectedLevel"])
        ):
            raise ValueError("Invalid native level dimension preview.")
        items.append(
            {
                "index": index,
                "status": "ready",
                "before": row,
                "parameters": {**p, "expectedLevel": row["expectedLevel"]},
            }
        )
    return {"operation": operation, "target": target, "items": items}


def _mismatches(item, row):
    before = item["before"]
    expected = {
        "type": "LevelDimension",
        "floorIndex": before["floorIndex"],
        "position": before["position"],
        "level": before["expectedLevel"],
        "staticLevel": False,
        "parentElementId": {"guid": before["slabGuid"]},
        "origin": before["origin"],
        "parentTypeId": 8,
        "note1": {"contentType": 0},
        "settings": before["settings"],
    }
    return write._mismatches(expected, row)


async def _dispatch(client, receipt):
    ready = [i for i in receipt["items"] if i["status"] == "ready"]
    if not ready:
        return
    port, timeout = receipt["target"]["port"], receipt["write_timeout_seconds"]
    receipt["undo_scope"] = "One Undo step: Create Level Dimensions."
    try:
        raw = await _addon(
            client,
            port,
            "CreateLevelDimensions",
            {"dimensions": [i["parameters"] for i in ready]},
            timeout,
        )
        rows = _rows(raw, len(ready))
    except AddOnError as exc:
        for item in ready:
            item.update(status="failed", error=exc.detail or str(exc))
        return
    except (ArchicadError, ValueError) as exc:
        return solids._unknown(receipt, str(exc))
    created = []
    for item, row in zip(ready, rows, strict=True):
        item["create_response"] = row
        if not isinstance(row, dict) or "error" in row:
            item.update(status="failed", error=row)
            continue
        try:
            guid = str(UUID(row["elementId"]["guid"])).upper()
        except (KeyError, ValueError, TypeError):
            item.update(status="unknown", error="Missing created GUID; inspect before retrying.")
            continue
        item.update(element_guid=guid, status="unverified")
        created.append(item)
    if not created:
        return
    try:
        raw = await _addon(
            client,
            port,
            "GetLevelDimensions",
            {"guids": [i["element_guid"] for i in created]},
            timeout,
        )
        rows = _rows(raw, len(created))
        for item, row in zip(created, rows, strict=True):
            differences = _mismatches(item, row)
            differences += write._mismatches({"elementId": {"guid": item["element_guid"]}}, row)
            item.update(
                after=row,
                mismatches=differences,
                status="verification_failed" if differences else "verified",
            )
    except (ArchicadError, ValueError, TypeError) as exc:
        receipt["verification_error"] = str(exc)


async def create_level_dimensions(
    client, dimensions, port=None, dry_run=True, confirmation_token=None
):
    """Preview/create 1..20 native, measured, slab-top associative level dimensions.

    Straight-edge top-reference slabs only; position must be in the slab, outside holes.
    Single measured note, project-zero origin. Favorite must be LevelDimension.
    Explicit apply port and single-use token; per-item receipt and separate native getter.
    Never saves, deletes, creates a Label or changes model geometry/tool defaults.
    """
    if not 1 <= len(dimensions) <= 20:
        raise ValueError("Pass 1 to 20 level dimensions.")
    validated = [
        d if isinstance(d, LevelDimension) else LevelDimension.model_validate(d) for d in dimensions
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
