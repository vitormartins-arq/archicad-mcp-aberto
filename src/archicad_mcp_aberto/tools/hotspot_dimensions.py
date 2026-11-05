"""Linear dimensions between element hotspots, through the ArchicadMcpAberto add-on (addon/).

Tapir has no command that reads hotspots, and it does not apply the text settings of a
Dimension favorite. Our add-on reads hotspots with their coordinates and neig data, reads
what a favorite holds, creates associative linear dimensions and reads them back with their
witness points and text.

A witness point names an element and one of its references: ``in_index`` from
list_element_hotspots, or ``reference: "origin"`` for the hotspot on the object's own origin,
chosen by comparing coordinates because a library part's hotspot order can change with its
settings. A reference that is not a hotspot, such as a wall face, takes ``line: true`` with
``in_index`` and ``location``: on Archicad 30, in_index 11 is the wall edge through polygon
hotspots 1 and 2 and 21 the edge through 3 and 4. The dimension's direction must be exactly
perpendicular to that face, not rounded, or Archicad drops the point later. Never saves.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from archicad_mcp_aberto.connection import (
    AddOnError,
    ArchicadClient,
    ArchicadError,
    CommandNotRegistered,
    resolve_port,
)
from archicad_mcp_aberto.tools import scenes, solids, write

MAX_DIMENSIONS = 50
MAX_ELEMENTS = 200
TOLERANCE = 0.001  # metres
# What a dimension must keep from its favorite. "static" is left out: these are associative.
# So is "textDirection": live on AC30, a favorite holding 0 gives a dimension holding 1.
COMPARED_SETTINGS = (
    "layerIndex",
    "linePen",
    "textPosition",
    "appearance",
    "witnessForm",
    "witnessValue",
    "witnessExtensionPen",
    "marker.type",
    "marker.pen",
    "marker.size",
    "note.pen",
    "note.fontIndex",
    "note.size",
    "note.faceBits",
    "note.frame",
    "note.opaque",
    "note.backgroundPen",
)


class Point2D(write.InputModel):
    x: float
    y: float

    @model_validator(mode="after")
    def finite(self) -> Point2D:
        if not (math.isfinite(self.x) and math.isfinite(self.y)):
            raise ValueError("Coordinates must be finite.")
        return self


class Witness(write.InputModel):
    element_guid: str
    in_index: int | None = None
    reference: Literal["origin"] | None = None
    line: bool = False
    special: int | None = None
    location: Point2D | None = None

    @field_validator("element_guid")
    @classmethod
    def canonical_guid(cls, value: str) -> str:
        return str(UUID(value)).upper()

    @model_validator(mode="after")
    def one_reference(self) -> Witness:
        if (self.in_index is None) == (self.reference is None):
            raise ValueError("Give either in_index or reference.")
        if self.line and (self.reference is not None or self.location is None):
            raise ValueError("A line reference needs in_index and location.")
        return self


class LinearDimension(write.InputModel):
    reference_point: Point2D
    direction: Point2D
    witnesses: Annotated[list[Witness], Field(min_length=2, max_length=50)]

    @model_validator(mode="after")
    def sound(self) -> LinearDimension:
        if self.direction.x == 0 and self.direction.y == 0:
            raise ValueError("The direction must be non-zero.")
        return self


async def _addon(client, port, name, parameters=None, timeout=None):
    try:
        return await client.own_addon(port, name, parameters, timeout=timeout)
    except CommandNotRegistered as exc:
        raise AddOnError(scenes.ADDON_MISSING, exc.code, exc.detail) from exc


def _rows(response: dict, count: int, command: str) -> list[dict]:
    rows = response.get("elements")
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueError(f"Unexpected {command} response.")
    return rows


def _ids(guids: list[str]) -> list[dict]:
    return [{"elementId": {"guid": g}} for g in guids]


def _guids(element_guids: list[str]) -> list[str]:
    if not 1 <= len(element_guids) <= MAX_ELEMENTS:
        raise ValueError(f"Pass between 1 and {MAX_ELEMENTS} elements.")
    return [str(UUID(g)).upper() for g in element_guids]


async def list_element_hotspots(
    client: ArchicadClient, element_guids: list[str], port: int | None = None
) -> dict:
    """Every hotspot of each element: x, y, z, neigId and inIndex, plus an object's origin."""
    guids = _guids(element_guids)
    port = await resolve_port(client, port)
    response = await _addon(client, port, "GetElementHotspots", {"elements": _ids(guids)})
    return {"port": port, "elements": _rows(response, len(guids), "GetElementHotspots")}


async def get_dimension_favorite(
    client: ArchicadClient, name: str, port: int | None = None
) -> dict:
    """What a Dimension favorite holds: layer, pens, marker, witness lines and text."""
    port = await resolve_port(client, port)
    return {"port": port, **await _addon(client, port, "GetDimensionFavorite", {"name": name})}


async def get_dimensions(
    client: ArchicadClient, element_guids: list[str], port: int | None = None
) -> dict:
    """Dimensions as they are: settings, line, witness points, measured values and text."""
    guids = _guids(element_guids)
    port = await resolve_port(client, port)
    response = await _addon(client, port, "GetDimensions", {"elements": _ids(guids)})
    return {"port": port, "elements": _rows(response, len(guids), "GetDimensions")}


def _origin_hotspot(row: dict, label: str) -> dict:
    origin = row.get("origin")
    if not isinstance(origin, dict):
        raise ValueError(f"{label}: this element has no object origin.")
    for hotspot in row.get("hotspots", []):
        if (
            abs(hotspot.get("x", math.inf) - origin["x"]) <= TOLERANCE
            and abs(hotspot.get("y", math.inf) - origin["y"]) <= TOLERANCE
        ):
            return hotspot
    raise ValueError(f"{label}: no hotspot sits on the object's origin.")


def _witness(witness: Witness, row: dict, label: str) -> dict:
    if "error" in row:
        raise ValueError(f"{label}: cannot read the hotspots of {witness.element_guid}.")
    if witness.reference == "origin":
        hotspot = _origin_hotspot(row, label)
    elif witness.line:
        hotspot = {"inIndex": witness.in_index, **witness.location.model_dump()}
    else:
        hotspot = next(
            (h for h in row.get("hotspots", []) if h.get("inIndex") == witness.in_index), None
        )
        if hotspot is None:
            raise ValueError(f"{label}: element has no hotspot with in_index {witness.in_index}.")
    out = {
        "elementId": {"guid": witness.element_guid},
        "inIndex": hotspot["inIndex"],
        "location": {"x": hotspot["x"], "y": hotspot["y"]},
    }
    if witness.line:
        out["line"] = True
    if witness.special is not None:
        out["special"] = witness.special
    return out


def _signature(witnesses: list[dict], direction: dict) -> tuple:
    """Same references along the same line, whichever way round either is listed."""
    length = math.hypot(direction["x"], direction["y"]) or 1.0
    x, y = direction["x"] / length, direction["y"] / length
    if x < -1e-6 or (abs(x) <= 1e-6 and y < 0):
        x, y = -x, -y
    points = sorted(
        (str((w.get("elementId") or {}).get("guid", "")).upper(), w.get("inIndex"))
        for w in witnesses
    )
    return tuple(points), round(x, 4) + 0.0, round(y, 4) + 0.0


async def _existing_signatures(client, port) -> dict[tuple, str]:
    listed = await client.tapir(port, "GetElementsByType", {"elementType": "Dimension"})
    guids = [e["elementId"]["guid"].upper() for e in listed.get("elements", [])]
    out = {}
    for start in range(0, len(guids), 500):
        chunk = guids[start : start + 500]
        response = await _addon(client, port, "GetDimensions", {"elements": _ids(chunk)})
        for guid, row in zip(chunk, _rows(response, len(chunk), "GetDimensions"), strict=True):
            if "error" not in row and isinstance(row.get("direction"), dict):
                out[_signature(row.get("witnessPoints") or [], row["direction"])] = guid
    return out


async def _measured_elements(client, guids, port):
    """A dimension changes nothing in what it measures, so a locked element is fine."""
    port, target, _ = await write._context(client, port)
    result = await client.tapir(
        port,
        "GetDetailsOfElements",
        {"elements": _ids(guids), "fields": write.DETAIL_FIELDS},
    )
    rows = result.get("detailsOfElements")
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected element details response.")
    for guid, row in zip(guids, rows, strict=True):
        if not isinstance(row, dict) or "error" in row or row.get("type") in (None, "Unknown"):
            raise ValueError(f"Element {guid} does not exist or cannot be read.")
    return port, target, rows


async def _plan(client, plan_input, port, operation):
    dimensions, favorite = plan_input
    guids = list(dict.fromkeys(w.element_guid for d in dimensions for w in d.witnesses))
    if len(guids) > MAX_ELEMENTS:
        raise ValueError(f"Pass at most {MAX_ELEMENTS} different elements.")
    port, target, rows = await _measured_elements(client, guids, port)
    floors = {g: r.get("floorIndex") for g, r in zip(guids, rows, strict=True)}
    settings = None
    if favorite is not None:
        settings = (await _addon(client, port, "GetDimensionFavorite", {"name": favorite}))[
            "settings"
        ]
    response = await _addon(client, port, "GetElementHotspots", {"elements": _ids(guids)})
    hotspots = dict(zip(guids, _rows(response, len(guids), "GetElementHotspots"), strict=True))
    existing = await _existing_signatures(client, port)
    items = []
    for i, dimension in enumerate(dimensions):
        label = f"Dimension {i}"
        points = [_witness(w, hotspots[w.element_guid], label) for w in dimension.witnesses]
        stories = {floors[w.element_guid] for w in dimension.witnesses}
        if len(stories) != 1:
            raise ValueError(f"{label}: all witness elements must be on the same story.")
        floor = stories.pop()
        signature = _signature(points, dimension.direction.model_dump())
        if signature in existing:
            raise ValueError(f"{label}: dimension {existing[signature]} already measures this.")
        existing[signature] = f"of this plan, number {i},"
        item = {
            "index": i,
            "status": "ready",
            "floorIndex": floor,
            "parameters": {
                "floorIndex": floor,
                "referencePoint": dimension.reference_point.model_dump(),
                "direction": dimension.direction.model_dump(),
                "witnessPoints": points,
            },
        }
        if favorite is not None:
            item.update(favorite=favorite, favorite_settings=settings)
        items.append(item)
    return {
        "operation": operation,
        "target": target,
        "witness_elements": dict(zip(guids, rows, strict=True)),
        "items": items,
    }


def _setting(settings: dict, path: str):
    value = settings
    for key in path.split("."):
        value = value.get(key) if isinstance(value, dict) else None
    return value


def _same(first, second) -> bool:
    if isinstance(first, float | int) and isinstance(second, float | int):
        return abs(first - second) <= 1e-6
    return first == second


def _mismatches(item: dict, row: dict) -> list[str]:
    wanted = item["parameters"]["witnessPoints"]
    found = row.get("witnessPoints")
    if not isinstance(found, list) or len(found) != len(wanted):
        return ["witnessPoints"]
    problems = []
    if row.get("floorIndex") != item["floorIndex"]:
        problems.append("floorIndex")
    for n, (want, got) in enumerate(zip(wanted, found, strict=True)):
        guid = str((got.get("elementId") or {}).get("guid", "")).upper()
        if guid != want["elementId"]["guid"]:
            problems.append(f"witnessPoints.{n}.elementId")
        if got.get("inIndex") != want["inIndex"]:
            problems.append(f"witnessPoints.{n}.inIndex")
    settings = row.get("settings") or {}
    if "favorite_settings" in item:
        for path in COMPARED_SETTINGS:
            if not _same(_setting(settings, path), _setting(item["favorite_settings"], path)):
                problems.append(f"settings.{path}")
    problems.extend(row.get("textDifferences") or [])
    return problems


async def _dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    receipt["undo_scope"] = "The whole batch is one Undo step (Create Linear Dimensions)."
    parameters = {"dimensions": [i["parameters"] for i in items]}
    if "favorite" in items[0]:
        parameters["favorite"] = items[0]["favorite"]
    try:
        raw = await _addon(
            client, port, "CreateLinearDimensions", parameters, receipt["write_timeout_seconds"]
        )
    except AddOnError as exc:
        # The add-on answered with an error (or is not loaded): nothing was made.
        for item in items:
            item.update(status="failed", error=exc.detail or str(exc))
        return
    except ArchicadError as exc:
        return solids._unknown(receipt, f"CreateLinearDimensions: {exc}")
    rows = raw.get("elements")
    if not isinstance(rows, list) or len(rows) != len(items):
        return solids._unknown(receipt, "Unexpected CreateLinearDimensions response.")
    for item, row in zip(items, rows, strict=True):
        item["after"] = row
        if not isinstance(row, dict) or "error" in row:
            item.update(status="failed", error=row.get("error") if isinstance(row, dict) else row)
            continue
        guid = (row.get("elementId") or {}).get("guid")
        if not isinstance(guid, str):
            item.update(status="unknown", error="Missing ID or error; inspect Archicad.")
            continue
        problems = _mismatches(item, row)
        item.update(
            element_guid=guid.upper(), status="verification_failed" if problems else "verified"
        )
        if problems:
            item["mismatches"] = problems
    await _check_dimensions_kept(client, receipt)
    await _check_witness_elements(client, receipt)


async def _check_dimensions_kept(client, receipt):
    """Archicad can drop a witness point, or the whole dimension, after answering the create:
    live on AC30, with a line only nearly perpendicular to a wall face. Read them again."""
    created = [i for i in receipt["items"] if i["status"] == "verified"]
    if not created:
        return
    port = receipt["target"]["port"]
    try:
        response = await _addon(
            client,
            port,
            "GetDimensions",
            {"elements": _ids([i["element_guid"] for i in created])},
            receipt["write_timeout_seconds"],
        )
        rows = _rows(response, len(created), "GetDimensions")
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = f"Could not read the dimensions again: {exc}"
        return
    for item, row in zip(created, rows, strict=True):
        wanted = len(item["parameters"]["witnessPoints"])
        if "error" in row or len(row.get("witnessPoints") or []) != wanted:
            item.update(status="verification_failed", mismatches=["witness points dropped"])


async def _check_witness_elements(client, receipt):
    """A dimension must not touch what it measures: read those elements again."""
    before = receipt["witness_elements"]
    port, guids = receipt["target"]["port"], list(before)
    try:
        result = await client.tapir(
            port,
            "GetDetailsOfElements",
            {"elements": _ids(guids), "fields": write.DETAIL_FIELDS},
            timeout=receipt["write_timeout_seconds"],
        )
    except ArchicadError as exc:
        receipt["verification_error"] = f"Could not read the measured elements again: {exc}"
        return
    rows = result.get("detailsOfElements") or []
    changed = [g for g, row in zip(guids, rows, strict=False) if row != before[g]]
    if len(rows) != len(guids):
        changed = guids
    receipt["witness_elements_unchanged"] = not changed
    if changed:
        receipt["witness_elements_changed"] = changed
        for item in receipt["items"]:
            if item["status"] == "verified":
                item.update(status="verification_failed", mismatches=["witness elements changed"])


async def create_linear_dimensions(
    client: ArchicadClient,
    dimensions: list[dict | LinearDimension],
    favorite: str | None = None,
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 50 associative linear dimensions between hotspots, from one
    Dimension favorite or the tool defaults, on the story of their elements. Never saves."""
    if not 1 <= len(dimensions) <= MAX_DIMENSIONS:
        raise ValueError(f"Pass between 1 and {MAX_DIMENSIONS} dimensions.")
    validated = [
        d if isinstance(d, LinearDimension) else LinearDimension.model_validate(d)
        for d in dimensions
    ]
    return await write._write(
        client,
        (validated, favorite),
        port,
        dry_run,
        confirmation_token,
        "create_linear_dimensions",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
