"""Annotation draw order through documented Tapir 1.7.0 SetDetailsOfElements.

Source: ENZYME-APD/tapir-archicad-automation, commit 02691b5d,
archicad-addon/Sources/ElementCommands.cpp. No geometry or measurement points are sent.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Annotated
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.tools import edit, read, write

MAX_CHANGES = 50
# Restrict to annotation/2D types: embedded openings can indirectly change host order.
TYPES = {
    "Label",
    "Text",
    "Line",
    "PolyLine",
    "Arc",
    "Spline",
    "Hatch",
    "Dimension",
    "LevelDimension",
    "RadialDimension",
    "AngleDimension",
}
FIELDS = [*write.DETAIL_FIELDS, "drawIndex", "id"]


class DrawOrderChange(write.InputModel):
    guid: str
    draw_index: Annotated[int, Field(ge=1, le=14, strict=True)]

    @field_validator("guid")
    @classmethod
    def canonical_guid(cls, value):
        return str(UUID(value)).upper()


async def _details(client, port, guids, timeout=None):
    response = await client.tapir(
        port,
        "GetDetailsOfElements",
        {"elements": read.element_ids(guids), "fields": FIELDS},
        **({"timeout": timeout} if timeout is not None else {}),
    )
    rows = response.get("detailsOfElements")
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected annotation details response.")
    return rows


async def _plan(client, changes, port, operation):
    guids = [c.guid for c in changes]
    port, target, _ = await edit._editable(client, guids, port)
    rows = await _details(client, port, guids)
    items = []
    for index, (change, row) in enumerate(zip(changes, rows, strict=True)):
        if row.get("type") not in TYPES or "error" in row:
            raise ValueError(f"Item {index}: only supported annotation/2D types may change order.")
        current = row.get("drawIndex")
        if not isinstance(current, int) or isinstance(current, bool):
            raise ValueError(f"Item {index}: current drawIndex cannot be read.")
        items.append(
            {
                "index": index,
                "guid": change.guid,
                "status": "ready",
                "before": deepcopy(row),
                "requested_draw_index": change.draw_index,
                "parameters": {
                    "elementId": {"guid": change.guid},
                    "details": {"drawIndex": change.draw_index},
                },
            }
        )
    return {
        "operation": operation,
        "target": target,
        "items": items,
        "note": "Only display order changes. No measurement origin, leader or owner is moved. "
        "Opaque background and actual occlusion still require visual inspection.",
    }


async def _verify(client, receipt, items):
    rows = await _details(
        client,
        receipt["target"]["port"],
        [i["guid"] for i in items],
        receipt["write_timeout_seconds"],
    )
    for item, row in zip(items, rows, strict=True):
        expected = {**deepcopy(item["before"]), "drawIndex": item["requested_draw_index"]}
        mismatches = write._mismatches(expected, row)
        item.update(
            after=row,
            mismatches=mismatches,
            status="verification_failed" if mismatches else "verified",
        )


async def _dispatch(client, receipt):
    await edit._execute(client, receipt, "SetDetailsOfElements", "elementsWithDetails", _verify)


async def set_draw_order(client, changes, port=None, dry_run=True, confirmation_token=None):
    """Preview/apply annotation drawIndex 1..14, preserving all readable geometry/owners."""
    if not 1 <= len(changes) <= MAX_CHANGES:
        raise ValueError(f"Pass 1 to {MAX_CHANGES} annotation changes.")
    validated = [
        c if isinstance(c, DrawOrderChange) else DrawOrderChange.model_validate(c) for c in changes
    ]
    edit._unique([c.guid for c in validated], MAX_CHANGES)
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "set_draw_order",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
