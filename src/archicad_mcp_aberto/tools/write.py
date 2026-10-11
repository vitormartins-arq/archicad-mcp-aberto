"""Small, reviewable wall writes. Lengths are metres; no project is ever saved.

Previews live in one client session for ten minutes. A consumed preview is never
retried: an HTTP failure can happen after Archicad has already changed the model.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import time
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4
from weakref import WeakKeyDictionary

from pydantic import BaseModel, ConfigDict, Field, model_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError, resolve_port
from archicad_mcp_aberto.tools.read import element_ids

Positive = Annotated[float, Field(gt=0)]
MAX_WALLS = 20
MAX_SLABS = 20
PREVIEW_SECONDS = 600
DETAIL_FIELDS = ["type", "floorIndex", "layerIndex", "hotlinkId", "details"]


def write_timeout() -> float:
    """Seconds to wait for a write or its verification (ARCHICAD_MCP_WRITE_TIMEOUT).

    A CreateSlabs call on an upper story took over 12 s live on Archicad 30, so writes
    get a longer wait than reads before the outcome is reported as unknown.
    """
    value = float(os.environ.get("ARCHICAD_MCP_WRITE_TIMEOUT") or 120)
    if not math.isfinite(value) or value <= 0:
        raise ValueError("ARCHICAD_MCP_WRITE_TIMEOUT must be a positive number of seconds.")
    return value


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Point(InputModel):
    x: float
    y: float


class WallCreate(InputModel):
    start: Point
    end: Point
    floor_index: int
    height: Positive
    thickness: Positive
    bottom_offset: float = 0.0
    offset: float = 0.0
    reference_line: Literal["Outside", "Center", "Inside"] = "Center"

    @model_validator(mode="after")
    def nonzero_length(self) -> WallCreate:
        if math.hypot(self.start.x - self.end.x, self.start.y - self.end.y) < 1e-6:
            raise ValueError("A wall must have a reference line at least 0.000001 m long.")
        return self


class SlabCreate(InputModel):
    outline: Annotated[list[Point], Field(min_length=3, max_length=200)]
    floor_index: int
    thickness: Positive
    level: float

    @model_validator(mode="after")
    def simple_polygon(self) -> SlabCreate:
        points = self.outline
        if points[0] == points[-1]:
            points = points[:-1]
        if len(points) < 3 or len({(p.x, p.y) for p in points}) != len(points):
            raise ValueError("A slab needs at least three distinct vertices without repetitions.")
        edges = list(zip(points, points[1:] + points[:1], strict=True))
        if any(math.hypot(a.x - b.x, a.y - b.y) < 1e-6 for a, b in edges):
            raise ValueError("Slab edges must be at least 0.000001 m long.")
        # Translate before the shoelace sum to reduce cancellation far from the origin.
        origin = points[0]
        area = sum(
            (a.x - origin.x) * (b.y - origin.y) - (b.x - origin.x) * (a.y - origin.y)
            for a, b in edges
        )
        if not math.isfinite(area) or abs(area) < 1e-12:
            raise ValueError("A slab polygon must have nonzero finite area.")
        for i, (a, b) in enumerate(edges):
            c = points[(i + 2) % len(points)]
            cross = (b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x)
            dot = (b.x - a.x) * (c.x - b.x) + (b.y - a.y) * (c.y - b.y)
            if cross == 0 and dot < 0:
                raise ValueError("Adjacent slab edges must not overlap.")
        for i, (a, b) in enumerate(edges):
            for j, (c, d) in enumerate(edges[i + 1 :], i + 1):
                if j == i + 1 or (i == 0 and j == len(edges) - 1):
                    continue
                if _segments_intersect(a, b, c, d):
                    raise ValueError("A slab polygon must not intersect or touch itself.")
        self.outline = points
        return self


def _segments_intersect(a: Point, b: Point, c: Point, d: Point) -> bool:
    def cross(p, q, r):
        return (q.x - p.x) * (r.y - p.y) - (q.y - p.y) * (r.x - p.x)

    def on(p, q, r):
        return min(p.x, q.x) <= r.x <= max(p.x, q.x) and min(p.y, q.y) <= r.y <= max(p.y, q.y)

    ab_c, ab_d, cd_a, cd_b = cross(a, b, c), cross(a, b, d), cross(c, d, a), cross(c, d, b)
    return (
        (ab_c == 0 and on(a, b, c))
        or (ab_d == 0 and on(a, b, d))
        or (cd_a == 0 and on(c, d, a))
        or (cd_b == 0 and on(c, d, b))
        or ((ab_c > 0) != (ab_d > 0) and (cd_a > 0) != (cd_b > 0))
    )


@dataclass
class WriteState:
    session_id: UUID
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    previews: dict[str, tuple[float, dict]] = field(default_factory=dict)


_states: WeakKeyDictionary[ArchicadClient, WriteState] = WeakKeyDictionary()


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def _journal(receipt: dict, phase: str) -> str:
    """Write an atomic local receipt. Failure before dispatch prevents the write."""
    root = Path(
        os.environ.get("ARCHICAD_MCP_RECEIPTS_DIR")
        or str(Path.home() / ".archicad-mcp-aberto" / "receipts")
    ).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{receipt['receipt_id']}.{phase}.json"
    temporary = root / f"{receipt['receipt_id']}.{phase}.tmp"
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(receipt, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)
    return str(path.resolve())


async def _context(client: ArchicadClient, port: int | None) -> tuple[int, dict, list[int]]:
    port = await resolve_port(client, port)
    product = await client.command(port, "GetProductInfo")
    project = await client.tapir(port, "GetProjectInfo")
    tapir = await client.tapir(port, "GetAddOnVersion")
    stories = await client.tapir(port, "GetStories")
    elements = await client.command(port, "GetAllElements")
    target = {
        "port": port,
        "product": product,
        "project": project,
        "tapir": tapir,
        "stories": stories["stories"],
        "element_set_digest": _digest(
            sorted(e["elementId"]["guid"].upper() for e in elements["elements"])
        ),
    }
    return port, target, [s["index"] for s in stories["stories"]]


def _create_payload(wall: WallCreate) -> dict:
    return {
        "begCoordinate": wall.start.model_dump(),
        "endCoordinate": wall.end.model_dump(),
        "floorIndex": wall.floor_index,
        "height": wall.height,
        "thickness": wall.thickness,
        "zCoordinate": wall.bottom_offset,
        "offset": wall.offset,
        "arcAngle": 0.0,
        "structureType": "Basic",
        "referenceLineLocation": wall.reference_line,
    }


async def _plan(
    client: ArchicadClient, walls: list, port: int | None, operation: str = "create_walls"
) -> dict:
    port, target, floors = await _context(client, port)
    items = []
    slab = operation == "create_slabs"
    for index, wall in enumerate(walls):
        if wall.floor_index not in floors:
            raise ValueError(
                f"{'Slab' if slab else 'Wall'} {index}: story {wall.floor_index} does not exist."
            )
        payload = (
            {
                "polygonCoordinates": [p.model_dump() for p in wall.outline],
                "floorIndex": wall.floor_index,
                "thickness": wall.thickness,
                "level": wall.level,
                "referencePlaneLocation": "Top",
                "polygonArcs": [],
                "holes": [],
            }
            if slab
            else _create_payload(wall)
        )
        items.append({"index": index, "status": "ready", "parameters": payload})
    return {"operation": operation, "target": target, "items": items}


def _expected(item: dict) -> dict:
    parameters = item["parameters"]
    return {
        "type": "Wall",
        "floorIndex": parameters["floorIndex"],
        "details": {
            "geometryType": "Straight",
            "structureType": "Basic",
            "arcAngle": 0.0,
            "relativeTopStory": 0.0,
            "profileType": "Normal",
            "bottomOffset": parameters["zCoordinate"],
            "referenceLineLocation": parameters["referenceLineLocation"],
            "begCoordinate": parameters["begCoordinate"],
            "endCoordinate": parameters["endCoordinate"],
            "height": parameters["height"],
            "offset": parameters["offset"],
            "begThickness": parameters["thickness"],
        },
    }


def _mismatches(expected: Any, actual: Any, path: str = "") -> list[str]:
    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [path]
        return [
            mismatch
            for key, value in expected.items()
            for mismatch in _mismatches(value, actual.get(key), f"{path}.{key}".lstrip("."))
        ]
    if isinstance(expected, (float, int)) and not isinstance(expected, bool):
        if isinstance(actual, (float, int)) and not isinstance(actual, bool):
            if math.isclose(expected, actual, rel_tol=1e-9, abs_tol=1e-7):
                return []
        return [path]
    return [] if expected == actual else [path]


async def _dispatch(client: ArchicadClient, receipt: dict) -> None:
    items, port = receipt["items"], receipt["target"]["port"]
    slab = receipt["operation"] == "create_slabs"
    try:
        raw = await client.tapir(
            port,
            "CreateSlabs" if slab else "CreateWalls",
            {"slabsData" if slab else "wallsData": [i["parameters"] for i in items]},
            timeout=receipt["write_timeout_seconds"],
        )
    except ArchicadError as exc:
        for item in items:
            item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Write outcome is unknown. Inspect Archicad; do not retry this plan."
        return
    receipt["raw_response"] = raw
    rows = raw.get("elements")
    if not isinstance(rows, list) or len(rows) != len(items):
        for item in items:
            item.update(
                status="unknown", error="Unexpected response cardinality; inspect Archicad."
            )
        return
    succeeded = []
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        if not isinstance(row, dict):
            item.update(status="unknown", error="Unexpected element response.")
        elif "error" in row:
            item.update(status="failed", error=row["error"])
        elif isinstance(row.get("elementId"), dict):
            try:
                item["element_guid"] = str(UUID(row["elementId"]["guid"])).upper()
            except (ValueError, KeyError, TypeError, AttributeError):
                item.update(status="unknown", error="Invalid created element GUID.")
            else:
                succeeded.append(item)
        else:
            item.update(status="unknown", error="Missing element ID or error; inspect Archicad.")
    if not succeeded:
        return
    for item in succeeded:
        item["status"] = "unverified"
    try:
        verified = await client.tapir(
            port,
            "GetDetailsOfElements",
            {
                "elements": element_ids([i["element_guid"] for i in succeeded]),
                "fields": DETAIL_FIELDS,
            },
            timeout=receipt["write_timeout_seconds"],
        )
        after = verified.get("detailsOfElements")
        if not isinstance(after, list) or len(after) != len(succeeded):
            raise ValueError("Unexpected verification response cardinality.")
        for item, row in zip(succeeded, after, strict=True):
            item["after"] = row
            differences = (
                _slab_mismatches(item, row, receipt["target"])
                if slab
                else _mismatches(_expected(item), row)
            )
            item.update(status="verification_failed" if differences else "verified")
            if differences:
                item["mismatches"] = differences
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)


async def _write(
    client: ArchicadClient,
    walls: list,
    port: int | None,
    dry_run: bool,
    confirmation_token: str | None,
    operation: str = "create_walls",
) -> dict:
    if client.session_id is None:
        raise RuntimeError("ArchicadClient must be used inside 'async with'.")
    state = _states.get(client)
    if state is None or state.session_id != client.session_id:
        state = WriteState(session_id=client.session_id)
        _states[client] = state
    async with state.lock:
        if dry_run:
            plan = await _plan(client, walls, port, operation)
            now = time.monotonic()
            state.previews = {k: v for k, v in state.previews.items() if v[0] > now}
            if len(state.previews) >= 32:
                state.previews.pop(next(iter(state.previews)))
            token = str(uuid4())
            state.previews[token] = (now + PREVIEW_SECONDS, deepcopy(plan))
            return {
                **plan,
                "dry_run": True,
                "confirmation_token": token,
                "expires_in_seconds": PREVIEW_SECONDS,
                "note": "Review this plan with the user before applying. No model changes. "
                f"New {'slabs' if operation == 'create_slabs' else 'walls'} inherit "
                "Archicad's default layer and building material.",
            }
        if port is None:
            raise ValueError(
                f"Applying a {'slab' if operation == 'create_slabs' else 'wall'} "
                "plan requires its explicit port."
            )
        entry = state.previews.get(confirmation_token or "")
        if entry is None or entry[0] <= time.monotonic():
            raise ValueError("Preview missing, expired or already consumed. Run a new dry run.")
        plan = await _plan(client, walls, port, operation)
        if _digest(plan) != _digest(entry[1]):
            raise ValueError(
                "Parameters, target, stories or element IDs changed since preview. "
                "Run a new dry run."
            )
        timeout = write_timeout()
        receipt = {
            **deepcopy(plan),
            "write_timeout_seconds": timeout,
            "receipt_id": str(uuid4()),
            "dry_run": False,
            "started_at": datetime.now(UTC).isoformat(),
            "status": "outcome_unknown",
        }
        for item in receipt["items"]:
            item["slab_receipt_id" if operation == "create_slabs" else "wall_receipt_id"] = str(
                uuid4()
            )
        receipt["prepared_receipt_path"] = _journal(receipt, "prepared")
        # Consume before dispatch, including if dispatch or verification later fails.
        state.previews.pop(confirmation_token)
        await _dispatch(client, receipt)
        receipt["counts"] = {
            status: sum(i["status"] == status for i in receipt["items"])
            for status in (
                "verified",
                "failed",
                "unknown",
                "unverified",
                "verification_failed",
            )
        }
        receipt["status"] = (
            "verified" if receipt["counts"]["verified"] == len(receipt["items"]) else "needs_review"
        )
        receipt["finished_at"] = datetime.now(UTC).isoformat()
        receipt["note"] = "No project was saved. Use Archicad Undo to revert this batch."
        try:
            receipt["receipt_path"] = _journal(receipt, "result")
        except OSError as exc:
            receipt["receipt_error"] = str(exc)
            receipt["note"] += " Final receipt failed; keep this response and the prepared receipt."
        return receipt


async def create_walls(
    client: ArchicadClient,
    walls: list[dict | WallCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview or apply up to 20 straight Basic walls. Lengths are metres."""
    if not 1 <= len(walls) <= MAX_WALLS:
        raise ValueError(f"Pass between 1 and {MAX_WALLS} walls.")
    validated = [w if isinstance(w, WallCreate) else WallCreate.model_validate(w) for w in walls]
    return await _write(client, validated, port, dry_run, confirmation_token)


def _slab_mismatches(item: dict, row: Any, target: dict) -> list[str]:
    p = item["parameters"]
    story = next(s for s in target["stories"] if s["index"] == p["floorIndex"])
    expected = {
        "type": "Slab",
        "floorIndex": p["floorIndex"],
        "details": {
            "thickness": p["thickness"],
            "level": p["level"] - story["level"],
            "zCoordinate": p["level"],
            "referencePlaneLocation": "Top",
            "holes": [],
        },
    }
    differences = _mismatches(expected, row)
    details = row.get("details", {}) if isinstance(row, dict) else {}
    if not isinstance(details, dict):
        return differences
    outline = details.get("polygonOutline")
    wanted = p["polygonCoordinates"]
    if isinstance(outline, list) and len(outline) > 1 and not _mismatches(outline[0], outline[-1]):
        outline = outline[:-1]
    matches = False
    if isinstance(outline, list) and len(outline) == len(wanted):
        for sequence in (outline, list(reversed(outline))):
            for shift in range(len(sequence)):
                rotated = sequence[shift:] + sequence[:shift]
                if all(not _mismatches(a, b) for a, b in zip(wanted, rotated, strict=True)):
                    matches = True
    if not matches:
        differences.append("details.polygonOutline")
    if details.get("polygonArcs", []) != []:
        differences.append("details.polygonArcs")
    return differences


async def create_slabs(
    client: ArchicadClient,
    slabs: list[dict | SlabCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 simple slabs. Metres; level is absolute project Z.

    Straight edges, no holes; top reference plane. Layer/material inherit defaults.
    """
    if not 1 <= len(slabs) <= MAX_SLABS:
        raise ValueError(f"Pass between 1 and {MAX_SLABS} slabs.")
    validated = [s if isinstance(s, SlabCreate) else SlabCreate.model_validate(s) for s in slabs]
    return await _write(client, validated, port, dry_run, confirmation_token, "create_slabs")
