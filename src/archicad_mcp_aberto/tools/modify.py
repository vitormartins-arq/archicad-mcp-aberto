"""Edits of existing slabs, columns, beams, windows, doors and objects (Tapir Modify*).

Every tool follows modify_walls: a dry run first, a single-use token and the explicit
port to apply, per-element receipts and a read-back of each changed field. Fields are
Tapir's native camelCase names, in metres. Nothing is ever saved.

Levels are offsets from the element's own story. Tapir 1.7.0 takes an absolute
zCoordinate for slabs and objects and picks the story from it, so a change that would
move the element to another story is refused instead of silently re-homing it.
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Annotated, Any
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import edit, read, write

MAX_EDITS = 50


class _Edit(write.InputModel):
    guid: str

    @field_validator("guid")
    @classmethod
    def canonical_guid(cls, value):
        return str(UUID(value)).upper()

    @model_validator(mode="after")
    def has_changes(self):
        if not self.model_dump(exclude={"guid"}, exclude_none=True):
            raise ValueError("Supply at least one field to modify.")
        return self


class SlabModify(_Edit):
    thickness: write.Positive | None = None
    level: float | None = None


class ColumnModify(_Edit):
    origin: write.Point | None = None
    bottomOffset: float | None = None
    height: write.Positive | None = None
    width: write.Positive | None = None
    depth: write.Positive | None = None


class BeamModify(_Edit):
    begCoordinate: write.Point | None = None
    endCoordinate: write.Point | None = None
    level: float | None = None
    width: write.Positive | None = None
    height: write.Positive | None = None


class OpeningModify(_Edit):
    width: write.Positive | None = None
    height: write.Positive | None = None
    sillHeight: float | None = None
    centerOffset: Annotated[float, Field(ge=0)] | None = None


class Dimensions(write.InputModel):
    x: write.Positive
    y: write.Positive
    z: write.Positive


class ObjectModify(_Edit):
    origin: write.Point | None = None
    level: float | None = None
    dimensions: Dimensions | None = None


def _number(details, key, label):
    value = details.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{label}: cannot read the current {key}.")
    return value


def _story(target, row):
    return next(s for s in target["stories"] if s["index"] == row["floorIndex"])


def _same_story(target, row, z, label):
    """Mirror Tapir's GetFloorIndexAndOffset: the highest story at or below z wins."""
    found = None
    for story in sorted(target["stories"], key=lambda s: s["index"]):
        if story["level"] > z:
            break
        found = story
    if (found["index"] if found else 0) != row["floorIndex"]:
        raise ValueError(
            f"{label}: that level would move the element to another story. "
            "Keep it at or above its story level and below the next story."
        )


def _section(changes, details, first, second, label):
    """Linked (or round) sections keep both sizes equal; send and expect both."""
    sizes = {k: changes[k] for k in (first, second) if k in changes}
    if not sizes:
        return {}
    linked = details.get("circleBased") is True or details.get("isWidthAndHeightLinked") is True
    if linked:
        if len(set(sizes.values())) != 1:
            raise ValueError(f"{label}: {first} and {second} are linked; pass one size.")
        size = next(iter(sizes.values()))
        return {first: size, second: size}
    return sizes


def _slab(change, row, target, label, extra):
    details, changes = row["details"], change.model_dump(exclude={"guid"}, exclude_none=True)
    parameters, expected = {}, {}
    if "thickness" in changes:
        if details.get("structureType") != "Basic":
            raise ValueError(f"{label}: direct thickness changes require a Basic slab.")
        _number(details, "thickness", label)
        parameters["thickness"] = expected["thickness"] = changes["thickness"]
    if "level" in changes:
        _number(details, "level", label)
        z = _story(target, row)["level"] + changes["level"]
        _same_story(target, row, z, label)
        parameters["zCoordinate"] = z
        expected.update(level=changes["level"], zCoordinate=z)
    return changes, parameters, expected


def _column(change, row, target, label, extra):
    details, changes = row["details"], change.model_dump(exclude={"guid"}, exclude_none=True)
    parameters, expected = {}, {}
    if "origin" in changes:
        parameters["origin"] = expected["origin"] = changes["origin"]
    if "bottomOffset" in changes:
        _number(details, "bottomOffset", label)
        parameters["bottomOffset"] = changes["bottomOffset"]
        expected.update(
            bottomOffset=changes["bottomOffset"],
            zCoordinate=_story(target, row)["level"] + changes["bottomOffset"],
        )
    if "height" in changes:
        _number(details, "height", label)
        parameters["height"] = expected["height"] = changes["height"]
        expected["relativeTopStory"] = 0  # Tapir unlinks the top when height is set.
    section = _section(changes, details, "width", "depth", label)
    for key in section:
        _number(details, key, label)
    parameters.update(section)
    expected.update(section)
    return changes, parameters, expected


def _beam(change, row, target, label, extra):
    details, changes = row["details"], change.model_dump(exclude={"guid"}, exclude_none=True)
    arc = details.get("arcAngle")
    if (
        details.get("beamShape") != "Straight"
        or not isinstance(arc, (int, float))
        or isinstance(arc, bool)
        or not math.isfinite(arc)
        or abs(arc) > 1e-9
    ):
        raise ValueError(f"{label}: curved beams are refused.")
    parameters, expected = {}, {}
    start = changes.get("begCoordinate", details.get("begCoordinate"))
    end = changes.get("endCoordinate", details.get("endCoordinate"))
    if not isinstance(start, dict) or not isinstance(end, dict):
        raise ValueError(f"{label}: beam endpoints are required for safe editing.")
    start = write.Point.model_validate(start).model_dump()
    end = write.Point.model_validate(end).model_dump()
    if math.hypot(start["x"] - end["x"], start["y"] - end["y"]) < 1e-6:
        raise ValueError(f"{label}: the resulting beam would have zero length.")
    for key in ("begCoordinate", "endCoordinate"):
        if key in changes:
            parameters[key] = expected[key] = changes[key]
    if "level" in changes:
        _number(details, "level", label)
        parameters["level"] = changes["level"]
        expected.update(
            level=changes["level"], zCoordinate=_story(target, row)["level"] + changes["level"]
        )
    section = _section(changes, details, "width", "height", label)
    for key in section:
        _number(details, key, label)
    parameters.update(section)
    expected.update(section)
    if expected:
        expected.update(beamShape="Straight", arcAngle=0.0)
    return changes, parameters, expected


def _opening(change, row, target, label, extra):
    details, changes = row["details"], change.model_dump(exclude={"guid"}, exclude_none=True)
    owner = details.get("ownerElementId")
    if details.get("ownerElementType") != "Wall" or not isinstance(owner, dict):
        raise ValueError(f"{label}: only openings in walls are supported.")
    for key in changes:
        _number(details, key, label)
    if "centerOffset" in changes:
        wall = extra.get(str(owner.get("guid", "")).upper())
        wall_details = wall.get("details") if isinstance(wall, dict) else None
        if not isinstance(wall_details, dict) or wall_details.get("geometryType") != "Straight":
            raise ValueError(f"{label}: moving an opening needs its straight owner wall.")
        begin, end = wall_details.get("begCoordinate"), wall_details.get("endCoordinate")
        if not isinstance(begin, dict) or not isinstance(end, dict):
            raise ValueError(f"{label}: the owner wall has no reference line coordinates.")
        length = math.hypot(end["x"] - begin["x"], end["y"] - begin["y"])
        if changes["centerOffset"] > length + 1e-6:
            raise ValueError(
                f"{label}: centerOffset {changes['centerOffset']} m is past the wall end "
                f"({length:.3f} m long)."
            )
    return changes, dict(changes), dict(changes)


def _object(change, row, target, label, extra):
    details, changes = row["details"], change.model_dump(exclude={"guid"}, exclude_none=True)
    parameters, expected = {}, {}
    if "origin" in changes or "level" in changes:
        origin = details.get("origin")
        if not isinstance(origin, dict):
            raise ValueError(f"{label}: cannot read the current origin.")
        coordinates = {
            "x": changes.get("origin", origin)["x"],
            "y": changes.get("origin", origin)["y"],
            "z": (
                _story(target, row)["level"] + changes["level"]
                if "level" in changes
                else _number(origin, "z", label)
            ),
        }
        _same_story(target, row, coordinates["z"], label)
        parameters["coordinates"] = coordinates
        expected["origin"] = coordinates
    if "dimensions" in changes:
        if not isinstance(details.get("dimensions"), dict):
            raise ValueError(f"{label}: cannot read the current dimensions.")
        parameters["dimensions"] = expected["dimensions"] = changes["dimensions"]
    return changes, parameters, expected


async def _owner_walls(client, port, rows):
    guids = []
    for row in rows:
        details = row.get("details")
        owner = details.get("ownerElementId") if isinstance(details, dict) else None
        if isinstance(owner, dict) and isinstance(owner.get("guid"), str):
            guids.append(owner["guid"].upper())
    guids = list(dict.fromkeys(guids))
    if not guids:
        return {}
    response = await client.tapir(
        port, "GetDetailsOfElements", {"elements": read.element_ids(guids), "fields": ["details"]}
    )
    walls = response.get("detailsOfElements")
    if not isinstance(walls, list) or len(walls) != len(guids):
        raise ValueError("Unexpected owner wall details response.")
    return dict(zip(guids, walls, strict=True))


# operation -> (element types accepted, Tapir command, list key, field planner)
SPECS = {
    "modify_slabs": (("Slab",), "ModifySlabs", "slabsWithDetails", _slab),
    "modify_columns": (("Column",), "ModifyColumns", "columnsWithDetails", _column),
    "modify_beams": (("Beam",), "ModifyBeams", "beamsWithDetails", _beam),
    "modify_windows": (("Window",), "ModifyWindows", "windowsWithDetails", _opening),
    "modify_doors": (("Door",), "ModifyDoors", "doorsWithDetails", _opening),
    "modify_objects": (("Object",), "ModifyObjects", "objectsWithDetails", _object),
}


async def _plan(client, edits, port, operation):
    types, _, _, fields = SPECS[operation]
    port, target, rows = await edit._editable(client, [e.guid for e in edits], port)
    extra: dict[str, Any] = {}
    if operation in ("modify_windows", "modify_doors"):
        extra = await _owner_walls(client, port, rows)
    items = []
    for index, (change, row) in enumerate(zip(edits, rows, strict=True)):
        label = f"{types[0]} {index} ({change.guid})"
        if row["type"] not in types or not isinstance(row.get("details"), dict):
            raise ValueError(f"{label}: is a {row['type']}, not a {types[0]} with details.")
        changes, parameters, expected = fields(change, row, target, label, extra)
        items.append(
            {
                "index": index,
                "status": "ready",
                "element_guid": change.guid,
                "type": row["type"],
                "floorIndex": row.get("floorIndex"),
                "layerIndex": row.get("layerIndex"),
                "before": deepcopy(row),
                "new": changes,
                "expected": expected,
                "parameters": {"elementId": {"guid": change.guid}, **parameters},
            }
        )
    return {"operation": operation, "target": target, "items": items}


async def _verify(client, receipt, items):
    response = await client.tapir(
        receipt["target"]["port"],
        "GetDetailsOfElements",
        {
            "elements": read.element_ids([i["element_guid"] for i in items]),
            "fields": write.DETAIL_FIELDS,
        },
        timeout=receipt["write_timeout_seconds"],
    )
    rows = response.get("detailsOfElements")
    if not isinstance(rows, list) or len(rows) != len(items):
        raise ValueError("Unexpected modified-element response cardinality.")
    for item, row in zip(items, rows, strict=True):
        item["after"] = row
        differences = write._mismatches(
            {
                "type": item["type"],
                "floorIndex": item["floorIndex"],
                "layerIndex": item["layerIndex"],
                "details": item["expected"],
            },
            row,
        )
        item["status"] = "verification_failed" if differences else "verified"
        if differences:
            item["mismatches"] = differences


async def _dispatch(client, receipt):
    _, command, key, _ = SPECS[receipt["operation"]]
    await edit._execute(client, receipt, command, key, _verify)


async def _modify(client, edits, model, port, dry_run, confirmation_token, operation):
    validated = [e if isinstance(e, model) else model.model_validate(e) for e in edits]
    edit._unique([e.guid for e in validated], MAX_EDITS)
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        operation,
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )


async def modify_slabs(
    client: ArchicadClient,
    slabs: list[dict | SlabModify],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/modify up to 50 slabs: thickness (Basic only) and level from its story."""
    return await _modify(
        client, slabs, SlabModify, port, dry_run, confirmation_token, "modify_slabs"
    )


async def modify_columns(
    client: ArchicadClient,
    columns: list[dict | ColumnModify],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/modify up to 50 columns: origin, bottomOffset, height, width, depth.

    Setting height unlinks the top story, as Tapir does. Round or linked sections take
    one size for both width and depth.
    """
    return await _modify(
        client, columns, ColumnModify, port, dry_run, confirmation_token, "modify_columns"
    )


async def modify_beams(
    client: ArchicadClient,
    beams: list[dict | BeamModify],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/modify up to 50 straight beams: endpoints, level, width, height."""
    return await _modify(
        client, beams, BeamModify, port, dry_run, confirmation_token, "modify_beams"
    )


async def modify_windows(
    client: ArchicadClient,
    windows: list[dict | OpeningModify],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/modify up to 50 windows in walls: width, height, sillHeight, centerOffset."""
    return await _modify(
        client, windows, OpeningModify, port, dry_run, confirmation_token, "modify_windows"
    )


async def modify_doors(
    client: ArchicadClient,
    doors: list[dict | OpeningModify],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/modify up to 50 doors in walls: width, height, sillHeight, centerOffset."""
    return await _modify(
        client, doors, OpeningModify, port, dry_run, confirmation_token, "modify_doors"
    )


async def modify_objects(
    client: ArchicadClient,
    objects: list[dict | ObjectModify],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/modify up to 50 objects: origin (x, y), level from its story, dimensions.

    dimensions.z sets the library part's ZZYZX; a part without it fails verification.
    """
    return await _modify(
        client, objects, ObjectModify, port, dry_run, confirmation_token, "modify_objects"
    )
