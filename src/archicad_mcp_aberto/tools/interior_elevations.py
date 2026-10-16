"""New interior elevations from a chain of points (Tapir 1.7.0 CreateInteriorElevations).

Each consecutive pair of points, in metres, becomes one segment that looks to the LEFT of
its direction, as far as depth (Tapir's default is 1 m). Walking a room's corners
anticlockwise therefore looks at its walls from inside; closed=True repeats the first
point at the end so the last wall is included. Marker and settings come from the Interior
Elevation tool default. The name must be new in the Project Map, so the result can be
found back there; the optional id is the reference ID. Each one is read back as an
InteriorElevation element on its story and as InteriorElevationItem(s) of that name in
the Project Map. Never saves.
"""

from __future__ import annotations

import math
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import documents, sections, write

MAX_ITEMS = 20
MAX_NODES = 50
NAV_TYPE = "InteriorElevationItem"
Name = Annotated[str, Field(min_length=1, max_length=255)]
ReferenceId = Annotated[str, Field(min_length=1, max_length=255)]


class InteriorElevationCreate(write.InputModel):
    nodes: Annotated[list[write.Point], Field(min_length=2, max_length=MAX_NODES)]
    closed: bool = False
    floor_index: int
    name: Name
    reference_id: ReferenceId | None = None
    depth: sections.Depth = 1.0

    @field_validator("name", "reference_id")
    @classmethod
    def trimmed(cls, value: str | None) -> str | None:
        if value is not None and value != value.strip():
            raise ValueError("must not start or end with spaces.")
        return value

    @model_validator(mode="after")
    def segments_have_length(self) -> InteriorElevationCreate:
        chain = self.chain()
        if self.closed and len(self.nodes) < 3:
            raise ValueError("A closed interior elevation needs at least 3 points.")
        for a, b in zip(chain, chain[1:], strict=False):
            if math.hypot(a.x - b.x, a.y - b.y) < 1e-6:
                raise ValueError("Two consecutive points must not be at the same place.")
        return self

    def chain(self) -> list[write.Point]:
        return [*self.nodes, self.nodes[0]] if self.closed else list(self.nodes)


async def _plan(client, items, port, operation):
    port, target, floors = await write._context(client, port)
    tree = await documents._tree(client, port, "ProjectMap")
    taken = {str(r["name"]).casefold() for r in tree if r["type"] == NAV_TYPE}
    seen, planned = set(), []
    for index, item in enumerate(items):
        label = f"Interior elevation {index}"
        if item.floor_index not in floors:
            raise ValueError(f"{label}: story {item.floor_index} does not exist.")
        key = item.name.casefold()
        if key in taken:
            raise ValueError(f"{label}: {item.name!r} already exists in the Project Map.")
        if key in seen:
            raise ValueError(f"{label}: {item.name!r} appears twice.")
        seen.add(key)
        chain = item.chain()
        parameters = {
            "nodeCoordinates": [p.model_dump() for p in chain],
            "depth": item.depth,
            "name": item.name,
            "floorIndex": item.floor_index,
        }
        if item.reference_id is not None:
            parameters["id"] = item.reference_id
        planned.append(
            {
                "index": index,
                "status": "ready",
                "name": item.name,
                "floorIndex": item.floor_index,
                "segments": len(chain) - 1,
                "parameters": parameters,
            }
        )
    return {"operation": operation, "target": target, "items": planned}


def _check(item: dict, row) -> list[str]:
    expected = {"type": "InteriorElevation", "floorIndex": item["parameters"]["floorIndex"]}
    return write._mismatches(expected, row)


async def _dispatch(client, receipt):
    await write._dispatch(client, receipt, _check)
    await sections._find_in_project_map(client, receipt, NAV_TYPE, segments=True)


async def create_interior_elevations(
    client: ArchicadClient,
    interior_elevations: list[dict | InteriorElevationCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 interior elevations from point chains (metres)."""
    if not 1 <= len(interior_elevations) <= MAX_ITEMS:
        raise ValueError(f"Pass between 1 and {MAX_ITEMS} interior elevations.")
    validated = [
        i if isinstance(i, InteriorElevationCreate) else InteriorElevationCreate.model_validate(i)
        for i in interior_elevations
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_interior_elevations",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
