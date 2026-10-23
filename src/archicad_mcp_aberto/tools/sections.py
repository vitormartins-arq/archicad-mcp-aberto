"""New straight sections on a story (Tapir 1.7.0 CreateSections).

Each section is a straight cut line from start to end, in metres, that looks to the
LEFT of the start-to-end direction, as far as depth (Tapir's default is 1 m). The marker
and every other setting come from the Section tool default. The name must be new in the
Project Map, so each section can be found back there after it is created; the reference
ID is numbered by Archicad. Every section is read back as a CutPlane element on its story
and as a SectionItem of that name in the Project Map. Never saves.
"""

from __future__ import annotations

import math
from typing import Annotated, Any

from pydantic import Field, field_validator, model_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import documents, write

MAX_ITEMS = 20
NAV_TYPE = "SectionItem"
Name = Annotated[str, Field(min_length=1, max_length=255)]
Depth = Annotated[float, Field(gt=0.0, le=10000.0, allow_inf_nan=False)]


class SectionCreate(write.InputModel):
    start: write.Point
    end: write.Point
    floor_index: int
    name: Name
    depth: Depth = 1.0

    @field_validator("name")
    @classmethod
    def trimmed(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("must not start or end with spaces.")
        return value

    @model_validator(mode="after")
    def has_length(self) -> SectionCreate:
        if math.hypot(self.start.x - self.end.x, self.start.y - self.end.y) < 1e-6:
            raise ValueError("A section line must not have zero length.")
        return self


async def _plan(client, items, port, operation):
    port, target, floors = await write._context(client, port)
    tree = await documents._tree(client, port, "ProjectMap")
    taken = {str(r["name"]).casefold() for r in tree if r["type"] == NAV_TYPE}
    seen, planned = set(), []
    for index, item in enumerate(items):
        label = f"Section {index}"
        if item.floor_index not in floors:
            raise ValueError(f"{label}: story {item.floor_index} does not exist.")
        key = item.name.casefold()
        if key in taken:
            raise ValueError(f"{label}: {item.name!r} already exists in the Project Map.")
        if key in seen:
            raise ValueError(f"{label}: {item.name!r} appears twice.")
        seen.add(key)
        planned.append(
            {
                "index": index,
                "status": "ready",
                "name": item.name,
                "floorIndex": item.floor_index,
                "parameters": {
                    "startCoordinate": item.start.model_dump(),
                    "endCoordinate": item.end.model_dump(),
                    "depth": item.depth,
                    "name": item.name,
                    "floorIndex": item.floor_index,
                },
            }
        )
    return {
        "operation": operation,
        "target": target,
        "items": planned,
        "warning": "Section markers inherit the Section tool defaults. If creation returns "
        "APIERR_BADID, initialize a valid Section marker in this test project or explicitly "
        "apply a Section favorite, then prepare a new preview. "
        "Defaults are never changed automatically.",
    }


def _check(item: dict, row: Any) -> list[str]:
    expected = {"type": "CutPlane", "floorIndex": item["parameters"]["floorIndex"]}
    return write._mismatches(expected, row)


async def _dispatch(client, receipt):
    await write._dispatch(client, receipt, _check)
    for item in receipt["items"]:
        if item.get("status") == "failed" and item.get("error", {}).get("code") == -2130313115:
            item["recovery_hint"] = (
                "Archicad returned APIERR_BADID. Check the Section tool marker/defaults and "
                "loaded library. Initialize a valid Section marker or explicitly apply an "
                "existing Section favorite, then prepare a new preview. No automatic retry."
            )
    await _find_in_project_map(client, receipt, NAV_TYPE)


async def _find_in_project_map(client, receipt, nav_type: str, segments: bool = False):
    """Match each verified item by name to its Project Map item(s).

    A section has exactly one item. An interior elevation (segments=True) may list one
    item per segment under the same name, so one or more is accepted there.
    """
    verified = [i for i in receipt["items"] if i["status"] == "verified"]
    if not verified:
        return
    port, timeout = receipt["target"]["port"], receipt["write_timeout_seconds"]
    try:
        tree = await documents._tree(client, port, "ProjectMap", timeout)
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = f"Project Map: {exc}"
        for item in verified:
            item["status"] = "unverified"
        return
    by_name: dict[str, list[dict]] = {}
    for row in tree:
        if row["type"] == nav_type:
            by_name.setdefault(str(row["name"]), []).append(row)
    for item in verified:
        found = by_name.get(item["name"], [])
        if segments and found:
            item["navigator_guids"] = [r["navigator_guid"] for r in found]
            item["reference_ids"] = [r["uiId"] for r in found]
        elif not segments and len(found) == 1:
            item["navigator_guid"] = found[0]["navigator_guid"]
            item["reference_id"] = found[0]["uiId"]
        else:
            item["status"] = "verification_failed"
            item.setdefault("mismatches", []).append(
                "navigator_name" if not found else "navigator_name_ambiguous"
            )


async def create_sections(
    client: ArchicadClient,
    sections: list[dict | SectionCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 straight sections: start, end, floor_index, name, depth."""
    if not 1 <= len(sections) <= MAX_ITEMS:
        raise ValueError(f"Pass between 1 and {MAX_ITEMS} sections.")
    validated = [
        s if isinstance(s, SectionCreate) else SectionCreate.model_validate(s) for s in sections
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_sections",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
