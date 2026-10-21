"""Openings of the Opening tool cut into existing walls or slabs, through Tapir 1.7.0.

``CreateOpenings`` places a rectangular opening (Archicad 26 or newer) in a host element
from a base point in absolute project metres and a positive width and height. Tapir sets
the opening's frame itself; since #533 the base point's z is the opening's bottom edge
on every Archicad version. Shape, extrusion and display settings come from the Opening
tool defaults. Tapir reports no opening-specific details, so the read-back checks the
new element's type and that the host lists it among its connected openings.
"""

from __future__ import annotations

import math
from uuid import UUID

from pydantic import field_validator, model_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import edit, write
from archicad_mcp_aberto.tools.read import element_ids

MAX_OPENINGS = 50
HOSTS = ("Wall", "Slab")


class Point3D(write.InputModel):
    x: float
    y: float
    z: float


class OpeningVoid(write.InputModel):
    owner_guid: str
    base_point: Point3D
    width: write.Positive
    height: write.Positive

    @field_validator("owner_guid")
    @classmethod
    def canonical_guid(cls, value: str) -> str:
        return str(UUID(value)).upper()

    @model_validator(mode="after")
    def finite(self):
        values = (*self.base_point.model_dump().values(), self.width, self.height)
        if not all(math.isfinite(v) for v in values):
            raise ValueError("Opening base point and size must be finite.")
        return self


async def _plan(client, openings, port, operation):
    owners = list(dict.fromkeys(o.owner_guid for o in openings))
    port, target, rows = await edit._editable(client, owners, port)
    types = {guid: row.get("type") for guid, row in zip(owners, rows, strict=True)}
    items = []
    for i, opening in enumerate(openings):
        if types[opening.owner_guid] not in HOSTS:
            raise ValueError(
                f"Opening {i}: element {opening.owner_guid} is a "
                f"{types[opening.owner_guid]}, not a wall or slab."
            )
        items.append(
            {
                "index": i,
                "status": "ready",
                "owner_guid": opening.owner_guid,
                "owner_type": types[opening.owner_guid],
                "parameters": {
                    "ownerElementId": {"guid": opening.owner_guid},
                    "basePoint": opening.base_point.model_dump(),
                    "width": opening.width,
                    "height": opening.height,
                },
            }
        )
    return {"operation": operation, "target": target, "items": items}


def _mismatches(item: dict, row) -> list[str]:
    return write._mismatches({"type": "Opening"}, row)


async def _dispatch(client, receipt):
    await write._dispatch(client, receipt, _mismatches)
    checked = [i for i in receipt["items"] if i["status"] == "verified"]
    if not checked:
        return
    owners = list(dict.fromkeys(i["owner_guid"] for i in checked))
    try:
        raw = await client.tapir(
            receipt["target"]["port"],
            "GetConnectedElements",
            {"elements": element_ids(owners), "connectedElementType": "Opening"},
        )
        rows = raw.get("connectedElements")
        if not isinstance(rows, list) or len(rows) != len(owners):
            raise ValueError("Unexpected connected elements response cardinality.")
        hosted = {}
        for owner, row in zip(owners, rows, strict=True):
            if not isinstance(row, dict) or not isinstance(row.get("elements"), list):
                raise ValueError(f"Connected openings of {owner} not read.")
            hosted[owner] = {e["elementId"]["guid"].upper() for e in row["elements"]}
    except (ArchicadError, ValueError, KeyError, TypeError, AttributeError) as exc:
        for item in checked:
            item.update(status="unverified", error=f"Host openings not read: {exc}")
        return
    for item in checked:
        if item["element_guid"].upper() not in hosted[item["owner_guid"]]:
            item["status"] = "verification_failed"
            item.setdefault("mismatches", []).append("owner")


async def create_openings(
    client: ArchicadClient,
    openings: list[dict | OpeningVoid],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/create up to 50 rectangular Opening-tool openings in existing editable walls
    or slabs (owner_guid): base_point x/y/z in absolute project metres (z is the bottom
    edge), positive width and height. Other settings take the Opening tool defaults.
    Reads back type and the host's connected openings; never saves.
    """
    if not 1 <= len(openings) <= MAX_OPENINGS:
        raise ValueError(f"Pass between 1 and {MAX_OPENINGS} openings.")
    entries = [o if isinstance(o, OpeningVoid) else OpeningVoid.model_validate(o) for o in openings]
    return await write._write(
        client,
        entries,
        port,
        dry_run,
        confirmation_token,
        "create_openings",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
