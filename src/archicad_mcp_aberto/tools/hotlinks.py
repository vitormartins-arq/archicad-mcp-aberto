"""Place hotlink modules from .mod or .pln files (Tapir 1.7.0).

place_hotlinks makes one hotlink node per source file (CreateHotlinkNodes; a node that
already points at the same file is reused, and then its name and story settings stay as
they are) and places each instance at an origin, rotation and mirroring on a story
(CreateHotlinkInstances). The other placement options keep the Hotlink tool defaults.
The source path is a file on the computer Archicad runs on; the MCP cannot check it
exists, so a wrong path fails that node and its instances. The read-back checks each new
element's type and story, and that its node is in GetHotlinks. Never saves.
"""

from __future__ import annotations

import re
from typing import Annotated, Any

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError, TapirError
from archicad_mcp_aberto.tools import read, write

MAX_PLACEMENTS = 20
ABSOLUTE = re.compile(r"^([A-Za-z]:[\\/]|\\\\|/)")


class Origin(write.InputModel):
    x: float
    y: float
    z: float = 0.0


class HotlinkPlace(write.InputModel):
    source_path: Annotated[str, Field(min_length=5, max_length=1024)]
    origin: Origin
    floor_index: int
    angle: float = 0.0
    mirrored: bool = False
    name: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    single_story: int | None = None  # the source story to place; None places all stories

    @field_validator("source_path")
    @classmethod
    def module_file(cls, value: str) -> str:
        if value != value.strip() or not ABSOLUTE.match(value):
            raise ValueError("source_path must be an absolute path without outer spaces.")
        if not value.lower().endswith((".mod", ".pln")):
            raise ValueError("source_path must be a .mod or .pln file.")
        return value


def _flatten(rows: Any, out: list[dict]) -> list[dict]:
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict):
            out.append(row)
            _flatten(row.get("children"), out)
    return out


async def _nodes(client, port, timeout=None) -> list[dict]:
    extra = {} if timeout is None else {"timeout": timeout}
    response = await client.tapir(port, "GetHotlinks", **extra)
    if not isinstance(response.get("hotlinks"), list):
        raise ValueError("Unexpected hotlinks response.")
    return _flatten(response["hotlinks"], [])


def _error(row: Any) -> Any:
    return row.get("error", row) if isinstance(row, dict) else row


def _node_guid(row: Any) -> str | None:
    value = row.get("hotlinkNodeId") if isinstance(row, dict) else None
    guid = value.get("guid") if isinstance(value, dict) else None
    return guid.upper() if isinstance(guid, str) else None


async def _plan(client, placements, port, operation):
    port, target, floors = await write._context(client, port)
    existing = {str(n.get("location", "")).casefold(): n for n in await _nodes(client, port)}
    sources: dict[str, dict] = {}
    items = []
    for index, place in enumerate(placements):
        if place.floor_index not in floors:
            raise ValueError(f"Hotlink {index}: story {place.floor_index} does not exist.")
        key = place.source_path.casefold()
        node = existing.get(key)
        settings = {"name": place.name, "single_story": place.single_story}
        if key in sources and sources[key]["settings"] != settings:
            raise ValueError(
                f"Hotlink {index}: the same file is asked with other name or story settings."
            )
        sources.setdefault(key, {"path": place.source_path, "settings": settings})
        instance: dict[str, Any] = {
            "origin": place.origin.model_dump(),
            "rotationAngle": place.angle,
            "mirrored": place.mirrored,
            "floorIndex": place.floor_index,
        }
        items.append(
            {
                "index": index,
                "status": "ready",
                "source_path": place.source_path,
                "node": "existing (its name and story settings are kept)" if node else "new",
                "existing_node_guid": _node_guid(node),
                "parameters": instance,
            }
        )
    nodes = []
    for source in sources.values():
        data: dict[str, Any] = {"sourceLocation": source["path"]}
        if source["settings"]["name"] is not None:
            data["name"] = source["settings"]["name"]
        if source["settings"]["single_story"] is not None:
            story = source["settings"]["single_story"]
            data.update(storyRangeType="SingleStory", refFloorIndex=story)
        nodes.append(data)
    return {
        "operation": operation,
        "target": target,
        "hotlink_nodes": nodes,
        "items": items,
    }


async def _dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]

    def unknown(error: str) -> None:
        for item in items:
            if item["status"] == "ready":
                item.update(status="unknown", error=error)
        receipt["warning"] = "Outcome is unknown. Inspect Archicad; do not retry this plan."

    try:
        raw = await client.tapir(
            port,
            "CreateHotlinkNodes",
            {"hotlinkNodes": receipt["hotlink_nodes"]},
            timeout=timeout,
        )
    except (TapirError, ArchicadError) as exc:
        return unknown(f"CreateHotlinkNodes: {exc}")
    rows = raw.get("hotlinkNodes")
    if not isinstance(rows, list) or len(rows) != len(receipt["hotlink_nodes"]):
        return unknown("Unexpected CreateHotlinkNodes response.")
    receipt["node_response"] = rows
    node_of = {}
    for data, row in zip(receipt["hotlink_nodes"], rows, strict=True):
        node_of[data["sourceLocation"].casefold()] = (_node_guid(row), row)
    placing = []
    for item in items:
        guid, row = node_of[item["source_path"].casefold()]
        if guid is None:
            item.update(status="failed", error=_error(row))
        else:
            item["node_guid"] = guid
            item["parameters"]["hotlinkNodeId"] = {"guid": guid}
            placing.append(item)
    if not placing:
        return
    try:
        raw = await client.tapir(
            port,
            "CreateHotlinkInstances",
            {"hotlinkInstances": [i["parameters"] for i in placing]},
            timeout=timeout,
        )
    except (TapirError, ArchicadError) as exc:
        return unknown(f"CreateHotlinkInstances: {exc}")
    receipt["raw_response"] = raw
    rows = raw.get("elements")
    if not isinstance(rows, list) or len(rows) != len(placing):
        return unknown("Unexpected CreateHotlinkInstances response.")
    placed = []
    for item, row in zip(placing, rows, strict=True):
        item["write_response"] = row
        value = row.get("elementId") if isinstance(row, dict) else None
        guid = value.get("guid") if isinstance(value, dict) else None
        if isinstance(guid, str):
            item.update(status="unverified", element_guid=guid.upper())
            placed.append(item)
        else:
            item.update(status="failed", error=_error(row))
    if not placed:
        return
    try:
        details = await client.tapir(
            port,
            "GetDetailsOfElements",
            {"elements": read.element_ids([i["element_guid"] for i in placed]),
             "fields": ["type", "floorIndex"]},
            timeout=timeout,
        )  # fmt: skip
        known = {_node_guid(n) for n in await _nodes(client, port, timeout)}
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    after = details.get("detailsOfElements")
    if not isinstance(after, list) or len(after) != len(placed):
        receipt["verification_error"] = "Unexpected element details response."
        return
    for item, row in zip(placed, after, strict=True):
        item["after"] = row
        problems = []
        if not isinstance(row, dict) or row.get("type") != "Hotlink":
            problems.append("type")
        elif row.get("floorIndex") != item["parameters"]["floorIndex"]:
            problems.append("floorIndex")
        if item["node_guid"] not in known:
            problems.append("node")
        item["status"] = "verification_failed" if problems else "verified"
        if problems:
            item["mismatches"] = problems


async def place_hotlinks(
    client: ArchicadClient,
    placements: list[dict | HotlinkPlace],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 hotlink module instances from .mod or .pln files."""
    if not 1 <= len(placements) <= MAX_PLACEMENTS:
        raise ValueError(f"Pass between 1 and {MAX_PLACEMENTS} placements.")
    validated = [
        p if isinstance(p, HotlinkPlace) else HotlinkPlace.model_validate(p) for p in placements
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "place_hotlinks",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
