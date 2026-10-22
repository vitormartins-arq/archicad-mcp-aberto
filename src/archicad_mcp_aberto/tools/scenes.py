"""3D scenes: read the rooms, shoot cameras, save the kept ones as View Map views.

Three steps, the workflow of docs/3D_SCENES.md:

1. ``read_scene_model`` reads the zones (name, number, area, 3D box) and the boxes of
   walls, columns, objects, doors, windows and curtain walls, with the official JSON API
   only, and suggests a first camera per room from its box.
2. ``shoot_3d_scenes`` sets each camera and returns the 3D window images, so the model
   can look at them, move the bad ones once and drop the rest.
3. ``save_3d_scenes`` saves the kept scenes as View Map views, one folder per room.

Shooting and saving use the ArchicadMcpAberto add-on (addon/): Get3DCamera, Set3DCamera,
Get3DCutPlanes, Set3DCutPlanes, Show3DAll, Get3DWindowImage and Save3DView. Both put the
3D camera and cut back as they found them. Nothing here edits elements or saves the
project; saved views are View Map items, outside Archicad's Undo.
"""

from __future__ import annotations

import base64
import binascii
import math
import time
from typing import Annotated, Any
from uuid import uuid4
from weakref import WeakKeyDictionary

from pydantic import BaseModel, Field, model_validator

from archicad_mcp_aberto.connection import (
    AddOnError,
    ArchicadClient,
    ArchicadError,
    CommandNotRegistered,
    resolve_port,
)
from archicad_mcp_aberto.tools.write import PREVIEW_SECONDS, _digest

MAX_SHOTS = 8
MAX_VIEWS = 60
MAX_ELEMENTS_PER_TYPE = 2000
ELEMENT_TYPES = ("Wall", "Column", "Object", "Door", "Window", "CurtainWall")
ZONE_PROPERTIES = ("Zone_ZoneName", "Zone_ZoneNumber", "Zone_CalculatedArea")
# Photographic defaults from docs/3D_SCENES.md.
EYE_HEIGHT = 1.30
WALL_INSET = 0.5
MIN_ROOM_AREA = 6.0
DEFAULT_VIEW_CONE = math.radians(60)
ADDON_MISSING = (
    "The ArchicadMcpAberto add-on is not loaded in this Archicad. Install the .apx of "
    "addon/ (Options > Add-On Manager, from a local copy) and restart Archicad."
)

Name = Annotated[str, Field(min_length=1, max_length=200)]


class Point3(BaseModel):
    x: float
    y: float
    z: float


class Target(BaseModel):
    x: float
    y: float
    z: float | None = None  # left out: camera height, so the camera stays level


class Parallel(BaseModel):
    azimuth: float | None = None  # radians
    projection_mode: int | None = None


class Scene(BaseModel):
    """One camera: a perspective (camera and target) or a parallel projection."""

    name: Name
    folder: Name | None = None
    camera: Point3 | None = None
    target: Target | None = None
    view_cone: Annotated[float, Field(gt=0.2, lt=2.6)] = DEFAULT_VIEW_CONE
    two_point: bool = False
    parallel: Parallel | None = None
    cut_height: float | None = None  # horizontal 3D cut, absolute metres; parallel only

    @model_validator(mode="after")
    def one_kind(self) -> Scene:
        if (self.parallel is None) == (self.camera is None):
            raise ValueError("Give either camera and target, or parallel.")
        if self.camera is not None:
            if self.target is None:
                raise ValueError("A perspective scene needs a target.")
            z = self.camera.z if self.target.z is None else self.target.z
            if (
                math.dist(
                    (self.camera.x, self.camera.y, self.camera.z), (self.target.x, self.target.y, z)
                )
                < 0.5
            ):
                raise ValueError("Camera and target must be at least 0.5 m apart.")
            if self.cut_height is not None:
                raise ValueError("cut_height is for parallel scenes only.")
        return self


def _box(row: Any) -> dict | None:
    box = row.get("boundingBox3D") if isinstance(row, dict) else None
    keys = ("xMin", "yMin", "zMin", "xMax", "yMax", "zMax")
    if not isinstance(box, dict) or not all(isinstance(box.get(k), int | float) for k in keys):
        return None
    return {k: round(float(box[k]), 3) for k in keys}


async def _boxes(client, port, elements: list[dict]) -> list[dict | None]:
    if not elements:
        return []
    raw = await client.command(port, "Get3DBoundingBoxes", {"elements": elements})
    rows = raw.get("boundingBoxes3D")
    if not isinstance(rows, list) or len(rows) != len(elements):
        raise ValueError("Unexpected bounding box response cardinality.")
    return [_box(row) for row in rows]


async def _zones(client, port) -> list[dict]:
    zones = (await client.command(port, "GetElementsByType", {"elementType": "Zone"})).get(
        "elements", []
    )
    if not zones:
        return []
    ids = (
        await client.command(
            port,
            "GetPropertyIds",
            {"properties": [{"type": "BuiltIn", "nonLocalizedName": n} for n in ZONE_PROPERTIES]},
        )
    ).get("properties")
    if not isinstance(ids, list) or len(ids) != len(ZONE_PROPERTIES):
        raise ValueError("Unexpected property id response for the zone properties.")
    values = (
        await client.command(
            port, "GetPropertyValuesOfElements", {"elements": zones, "properties": ids}
        )
    ).get("propertyValuesForElements")
    if not isinstance(values, list) or len(values) != len(zones):
        raise ValueError("Unexpected property value response cardinality.")
    boxes = await _boxes(client, port, zones)
    out = []
    for zone, row, box in zip(zones, values, boxes, strict=True):
        cells = row.get("propertyValues", []) if isinstance(row, dict) else []
        found = {}
        for key, cell in zip(("name", "number", "area"), cells, strict=False):
            value = cell.get("propertyValue", {}) if isinstance(cell, dict) else {}
            found[key] = value.get("value") if value.get("status", "normal") == "normal" else None
        area = found.get("area")
        out.append(
            {
                "guid": zone["elementId"]["guid"],
                "name": found.get("name"),
                "number": found.get("number"),
                "area": round(float(area), 2) if isinstance(area, int | float) else None,
                "box": box,
            }
        )
    return out


def suggest_cameras(zone: dict) -> dict:
    """First cameras for a room from its box: a one-point view along the longer side and,
    in big rooms, a two-point view from a corner. Boxes hide L shapes and furniture:
    the images decide."""
    box, area = zone.get("box"), zone.get("area")
    if box is None:
        return {"skip": "no 3D box"}
    width, depth = box["xMax"] - box["xMin"], box["yMax"] - box["yMin"]
    area = area if area is not None else width * depth
    if area < MIN_ROOM_AREA:
        return {"skip": f"smaller than {MIN_ROOM_AREA:g} m2"}
    z = round(box["zMin"] + EYE_HEIGHT, 2)
    along_x = width >= depth
    long_side, short_side = (width, depth) if along_x else (depth, width)
    if long_side < 2 * WALL_INSET + 1:
        return {"skip": "too narrow for a camera"}
    lateral = short_side / 2 + short_side / 6  # a third off the axis
    if along_x:
        camera = {"x": box["xMin"] + WALL_INSET, "y": box["yMin"] + lateral, "z": z}
        target = {"x": box["xMax"], "y": camera["y"]}
    else:
        camera = {"x": box["xMin"] + lateral, "y": box["yMin"] + WALL_INSET, "z": z}
        target = {"x": camera["x"], "y": box["yMax"]}
    cone = math.radians(60 if area >= 15 else 70)
    shots = [{"kind": "1P", "camera": camera, "target": target, "view_cone": round(cone, 4)}]
    if area >= 40:
        corner = {"x": box["xMax"] - WALL_INSET, "y": box["yMax"] - WALL_INSET, "z": z}
        # Aim so one wall takes about two thirds of the frame.
        aim = (
            {"x": box["xMin"], "y": box["yMin"] + depth / 3}
            if along_x
            else {"x": box["xMin"] + width / 3, "y": box["yMin"]}
        )
        shots.append(
            {
                "kind": "2P",
                "camera": corner,
                "target": aim,
                "view_cone": round(DEFAULT_VIEW_CONE, 4),
            }
        )
    return {"shots": shots}


async def read_scene_model(
    client: ArchicadClient,
    port: int | None = None,
    min_z: float | None = None,
    max_z: float | None = None,
) -> dict:
    """Rooms and element boxes to plan 3D scenes on; official JSON API only, no Tapir.

    min_z/max_z keep only elements whose box overlaps that height band (one story).
    """
    port = await resolve_port(client, port)
    zones = await _zones(client, port)
    for zone in zones:
        zone["suggested"] = suggest_cameras(zone)
    elements: dict[str, list] = {}
    truncated = []
    for kind in ELEMENT_TYPES:
        found = (await client.command(port, "GetElementsByType", {"elementType": kind})).get(
            "elements", []
        )
        if len(found) > MAX_ELEMENTS_PER_TYPE:
            truncated.append(kind)
            found = found[:MAX_ELEMENTS_PER_TYPE]
        rows = []
        for box in await _boxes(client, port, found):
            if box is None:
                continue
            if min_z is not None and box["zMax"] < min_z:
                continue
            if max_z is not None and box["zMin"] > max_z:
                continue
            rows.append([box[k] for k in ("xMin", "yMin", "xMax", "yMax", "zMin", "zMax")])
        elements[kind] = rows
    result: dict[str, Any] = {
        "port": port,
        "zones": zones,
        "element_boxes": elements,
        "box_order": ["xMin", "yMin", "xMax", "yMax", "zMin", "zMax"],
        "note": (
            "Suggested cameras come from room boxes only. Shoot them with shoot_3d_scenes, "
            "look at every image, move or drop the bad ones. Rules: docs/3D_SCENES.md."
        ),
    }
    if truncated:
        result["truncated_types"] = truncated
    return result


async def _addon(client, port, name, parameters=None):
    try:
        return await client.own_addon(port, name, parameters)
    except CommandNotRegistered as exc:
        raise AddOnError(ADDON_MISSING, exc.code, exc.detail) from exc


async def _snapshot(client, port) -> tuple[dict, dict]:
    return await _addon(client, port, "Get3DCamera"), await _addon(client, port, "Get3DCutPlanes")


async def _restore(client, port, state) -> None:
    camera, cut = state
    if camera.get("isPerspective"):
        keys = ("camera", "target", "viewCone", "twoPointPerspective")
        await _addon(
            client,
            port,
            "Set3DCamera",
            {"perspective": {k: camera[k] for k in keys if k in camera}},
        )
    else:
        keys = ("azimuth", "projectionMode")
        await _addon(
            client, port, "Set3DCamera", {"parallel": {k: camera[k] for k in keys if k in camera}}
        )
    await _addon(
        client, port, "Set3DCutPlanes", {k: cut[k] for k in ("enabled", "planes") if k in cut}
    )


def _cut(height: float | None) -> dict:
    if height is None:
        return {"enabled": False}
    # A horizontal cut at height h, read live on Archicad 30 (addon/CAMERA.md).
    return {
        "enabled": True,
        "planes": [{"cutStatus": 8, "pa": 0, "pb": 0, "pc": 1, "pd": height}],
    }


async def _set_scene(client, port, scene: Scene) -> dict:
    if scene.parallel is not None:
        parallel = {}
        if scene.parallel.azimuth is not None:
            parallel["azimuth"] = scene.parallel.azimuth
        if scene.parallel.projection_mode is not None:
            parallel["projectionMode"] = scene.parallel.projection_mode
        result = await _addon(client, port, "Set3DCamera", {"parallel": parallel})
        await _addon(client, port, "Set3DCutPlanes", _cut(scene.cut_height))
        await _addon(client, port, "Show3DAll", {"fitInWindow": True})
        return result
    await _addon(client, port, "Set3DCutPlanes", {"enabled": False})
    assert scene.camera is not None and scene.target is not None
    camera = scene.camera.model_dump()
    target = scene.target.model_dump()
    if target["z"] is None:
        target["z"] = camera["z"]
    return await _addon(
        client,
        port,
        "Set3DCamera",
        {
            "perspective": {
                "camera": camera,
                "target": target,
                "viewCone": scene.view_cone,
                "twoPointPerspective": scene.two_point,
            }
        },
    )


def _scenes(values, limit) -> list[Scene]:
    if not 1 <= len(values) <= limit:
        raise ValueError(f"Pass between 1 and {limit} scenes.")
    scenes = [v if isinstance(v, Scene) else Scene.model_validate(v) for v in values]
    if len({s.name for s in scenes}) != len(scenes):
        raise ValueError("Each scene name may appear only once per call.")
    return scenes


async def shoot_3d_scenes(
    client: ArchicadClient,
    scenes: list[dict | Scene],
    port: int | None = None,
    image_format: str = "jpg",
) -> tuple[dict, list[tuple[str, bytes]]]:
    """Set each scene in the 3D window and grab its image; put the 3D window back.

    Returns the report and (scene name, image bytes) pairs.
    """
    if image_format not in {"jpg", "png"}:
        raise ValueError("image_format is jpg or png.")
    entries = _scenes(scenes, MAX_SHOTS)
    port = await resolve_port(client, port)
    state = await _snapshot(client, port)
    report, images = [], []
    try:
        for scene in entries:
            try:
                await _set_scene(client, port, scene)
                raw = (await _addon(client, port, "Get3DWindowImage", {"format": image_format}))[
                    "image"
                ]
                images.append((scene.name, base64.b64decode(raw, validate=True)))
                report.append({"name": scene.name, "status": "shot"})
            except (ArchicadError, KeyError, binascii.Error) as exc:
                report.append({"name": scene.name, "status": "failed", "error": str(exc)})
    finally:
        await _restore(client, port, state)
    return {"port": port, "scenes": report, "restored": True}, images


# One-use save previews per client session: token -> (expiry, plan digest).
_previews: WeakKeyDictionary[ArchicadClient, dict[str, tuple[float, str]]] = WeakKeyDictionary()


async def save_3d_scenes(
    client: ArchicadClient,
    scenes: list[dict | Scene],
    folder_path: list[str],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Save scenes as View Map views under folder_path + each scene's folder.

    Dry run first; apply the same inputs with the explicit port and the one-use token.
    """
    entries = _scenes(scenes, MAX_VIEWS)
    if not 1 <= len(folder_path) <= 8 or any(not f or len(f) > 200 for f in folder_path):
        raise ValueError("folder_path needs 1 to 8 folder names of 1 to 200 characters.")
    if not dry_run and port is None:
        raise ValueError("Saving views requires the explicit port of the dry run.")
    port = await resolve_port(client, port)
    plan = [
        {"name": s.name, "folder_path": folder_path + ([s.folder] if s.folder else [])}
        for s in entries
    ]
    digest = _digest({"port": port, "scenes": [s.model_dump() for s in entries], "plan": plan})
    previews = _previews.setdefault(client, {})
    now = time.monotonic()
    for token in [t for t, (expiry, _) in previews.items() if expiry <= now]:
        previews.pop(token)
    if dry_run:
        await _addon(client, port, "Get3DCamera")  # fails early when the add-on is missing
        token = str(uuid4())
        previews[token] = (now + PREVIEW_SECONDS, digest)
        return {
            "port": port,
            "dry_run": True,
            "views": plan,
            "confirmation_token": token,
            "expires_in_seconds": PREVIEW_SECONDS,
            "note": (
                "Nothing saved yet. Show the list to the user, then repeat the same inputs with "
                "dry_run=false, this port and confirmation_token. Existing folders are reused; "
                "the first name may be a folder at any depth of the View Map."
            ),
        }
    entry = previews.pop(confirmation_token or "", None)
    if entry is None or entry[0] <= now:
        raise ValueError("Preview missing, expired or already consumed. Run a new dry run.")
    if entry[1] != digest:
        raise ValueError("Scenes, folders or port changed since the preview. Run a new dry run.")
    state = await _snapshot(client, port)
    saved = []
    try:
        for scene, row in zip(entries, plan, strict=True):
            try:
                await _set_scene(client, port, scene)
                result = await _addon(
                    client,
                    port,
                    "Save3DView",
                    {"name": scene.name, "folderPath": row["folder_path"]},
                )
                saved.append({**row, "status": "saved", "view_guid": result.get("viewGuid")})
            except ArchicadError as exc:
                saved.append({**row, "status": "failed", "error": str(exc)})
    finally:
        await _restore(client, port, state)
    return {
        "port": port,
        "dry_run": False,
        "views": saved,
        "saved": sum(v["status"] == "saved" for v in saved),
        "restored": True,
        "note": (
            "New views appear at the top of their folder. View Map changes are outside Undo; "
            "remove unwanted views by hand. The project was not saved."
        ),
    }
