"""3D scenes: read the rooms, shoot cameras, save the kept ones as View Map views.

Three steps, the workflow of docs/3D_SCENES.md:

1. ``read_scene_model`` reads the zones (name, number, area, 3D box) and the boxes of
   walls, columns, objects, doors, windows and curtain walls, with the official JSON API
   only, and suggests a first camera per room from its box.
2. ``shoot_3d_scenes`` sets each camera and returns the 3D window images, so the model
   can look at them, move the bad ones once and drop the rest.
3. ``save_3d_scenes`` saves the kept scenes in the View Map, one folder per room:
   every scene as a 3D view and each perspective also as a camera of one camera path
   (BIMx loads cameras faster than saved 3D views).

Shooting and saving use the ArchicadMcpAberto add-on (addon/): Get3DCamera, Set3DCamera,
Get3DCutPlanes, Set3DCutPlanes, Show3DAll, Get3DWindowImage, Save3DView and SaveCameraView.
Both put the 3D camera and cut back as they found them. Nothing here saves the project;
View Map items are outside Archicad's Undo, the camera elements are inside it.
"""

from __future__ import annotations

import base64
import binascii
import math
import re
import time
import unicodedata
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
DEFAULT_CAMERA_PATH = "00 BIMx - Apresentação"
MAX_ELEMENTS_PER_TYPE = 2000
ELEMENT_TYPES = ("Wall", "Column", "Object", "Door", "Window", "CurtainWall")
ZONE_PROPERTIES = ("Zone_ZoneName", "Zone_ZoneNumber", "Zone_CalculatedArea")
# Photographic defaults from docs/3D_SCENES.md.
EYE_HEIGHT = 1.30
WALL_INSET = 0.5
MIN_ROOM_AREA = 6.0
CAMERA_CLEARANCE = 0.3  # metres between a camera and a wall or column box
SIGHT_END_MARGIN = 0.4  # the last stretch of a sight line may touch the far wall
BLOCKING_TYPES = ("Wall", "Column", "CurtainWall", "Object")
# Rooms not worth a photograph (docs/3D_SCENES.md), matched as whole words, no accents.
SKIP_NAME_WORDS = {"DML", "DEPOSITO", "DEP", "ALMOXARIFADO", "SHAFT", "DESPENSA", "STORAGE"}
# Grabbing or saving a view waits on a full 3D redraw; a big model took over 12 s live.
SLOW_COMMAND_TIMEOUT = 60.0
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


def _plain(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return folded.upper()


def _skip_by_name(name: str | None) -> str | None:
    words = set(re.findall(r"[A-Z]+", _plain(name or "")))
    hit = words & SKIP_NAME_WORDS
    return f"service room ({sorted(hit)[0]})" if hit else None


def _inside(x: float, y: float, rect: tuple, margin: float = 0.0) -> bool:
    x0, y0, x1, y1 = rect
    return x0 - margin <= x <= x1 + margin and y0 - margin <= y <= y1 + margin


def _crosses(a: dict, b: dict, rect: tuple) -> bool:
    """Whether the 2D segment a-b passes through rect (Liang-Barsky)."""
    x0, y0, x1, y1 = rect
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, a["x"] - x0), (dx, x1 - a["x"]), (-dy, a["y"] - y0), (dy, y1 - a["y"])):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            t0 = max(t0, t)
        else:
            t1 = min(t1, t)
        if t0 > t1:
            return False
    return True


def _blockers(camera: dict, target: dict, obstacles: list[tuple]) -> int:
    # Stop short of the target: the far wall itself is what the photo looks at.
    length = math.dist((camera["x"], camera["y"]), (target["x"], target["y"]))
    keep = max(0.0, (length - SIGHT_END_MARGIN) / length) if length else 0.0
    end = {
        "x": camera["x"] + (target["x"] - camera["x"]) * keep,
        "y": camera["y"] + (target["y"] - camera["y"]) * keep,
    }
    return sum(_crosses(camera, end, rect) for rect in obstacles)


def _free(camera: dict, obstacles: list[tuple], rooms_inside: list[tuple]) -> bool:
    x, y = camera["x"], camera["y"]
    return not any(_inside(x, y, r, CAMERA_CLEARANCE) for r in obstacles) and not any(
        _inside(x, y, r) for r in rooms_inside
    )


def _pick(candidates: list[tuple[dict, dict]], obstacles, rooms_inside) -> tuple | None:
    """First candidate with a free camera and a clear sight line, else the least blocked."""
    scored = [
        (_blockers(cam, tgt, obstacles), i, cam, tgt)
        for i, (cam, tgt) in enumerate(candidates)
        if _free(cam, obstacles, rooms_inside)
    ]
    if not scored:
        return None
    blocked, _, camera, target = min(scored, key=lambda row: (row[0], row[1]))
    return camera, target, blocked


def suggest_cameras(
    zone: dict, obstacles: list[tuple] | None = None, rooms_inside: list[tuple] | None = None
) -> dict:
    """First cameras for a room from its box, checked against walls and columns.

    A one-point view along the longer side and, in big rooms, a two-point view from a
    corner. Each camera must stand clear of walls, columns and smaller rooms inside this
    room's box, and its sight line should cross none of them. obstacles and rooms_inside
    are [xMin, yMin, xMax, yMax] at eye height. Boxes still hide L shapes and furniture:
    the images decide.
    """
    obstacles = [tuple(r) for r in obstacles or []]
    rooms_inside = [tuple(r) for r in rooms_inside or []]
    box, area = zone.get("box"), zone.get("area")
    if box is None:
        return {"skip": "no 3D box"}
    service = _skip_by_name(zone.get("name"))
    if service:
        return {"skip": service}
    x0, y0, x1, y1 = box["xMin"], box["yMin"], box["xMax"], box["yMax"]
    width, depth = x1 - x0, y1 - y0
    area = area if area is not None else width * depth
    if area < MIN_ROOM_AREA:
        return {"skip": f"smaller than {MIN_ROOM_AREA:g} m2"}
    if max(width, depth) < 2 * WALL_INSET + 1:
        return {"skip": "too narrow for a camera"}
    z = round(box["zMin"] + EYE_HEIGHT, 2)

    def point(x, y, level=True):
        return {"x": round(x, 3), "y": round(y, 3), **({"z": z} if level else {})}

    # One point: along the longer side first, from either end, a third off the axis.
    candidates = []
    axes = ("x", "y") if width >= depth else ("y", "x")
    for axis in axes:
        for third in (2 / 3, 1 / 3):
            for forward in (True, False):
                if axis == "x":
                    y = y0 + depth * third
                    start, end = (x0 + WALL_INSET, x1) if forward else (x1 - WALL_INSET, x0)
                    candidates.append((point(start, y), point(end, y, False)))
                else:
                    x = x0 + width * third
                    start, end = (y0 + WALL_INSET, y1) if forward else (y1 - WALL_INSET, y0)
                    candidates.append((point(x, start), point(x, end, False)))
    shots, notes = [], []
    picked = _pick(candidates, obstacles, rooms_inside)
    cone = round(math.radians(60 if area >= 15 else 70), 4)
    if picked is None:
        notes.append("no free spot for a one-point camera")
    else:
        camera, target, blocked = picked
        shots.append({"kind": "1P", "camera": camera, "target": target, "view_cone": cone})
        if blocked:
            notes.append(f"1P sight line crosses {blocked} wall or column box(es)")
    if area >= 40:
        # Two point: from a corner, aimed so one wall takes about two thirds of the frame.
        corners = []
        for cx, cy, fx, fy in (
            (x1, y1, x0, y0),
            (x0, y0, x1, y1),
            (x1, y0, x0, y1),
            (x0, y1, x1, y0),
        ):
            sx = WALL_INSET if fx > cx else -WALL_INSET
            sy = WALL_INSET if fy > cy else -WALL_INSET
            aim = (fx, cy + (fy - cy) * 2 / 3) if width >= depth else (cx + (fx - cx) * 2 / 3, fy)
            corners.append((point(cx + sx, cy + sy), point(*aim, level=False)))
        picked = _pick(corners, obstacles, rooms_inside)
        if picked is not None:
            camera, target, blocked = picked
            two = round(DEFAULT_VIEW_CONE, 4)
            shots.append({"kind": "2P", "camera": camera, "target": target, "view_cone": two})
            if blocked:
                notes.append(f"2P sight line crosses {blocked} wall or column box(es)")
    if not shots:
        return {"skip": "no free spot for a camera"}
    result: dict[str, Any] = {"shots": shots}
    if notes:
        result["warnings"] = notes
    return result


def _label_rooms(zones: list[dict]) -> None:
    """A unique scene label per room: the zone name, plus its number when names repeat."""
    counts: dict[str, int] = {}
    for zone in zones:
        key = _plain(zone.get("name") or "")
        counts[key] = counts.get(key, 0) + 1
    used: set[str] = set()
    for index, zone in enumerate(zones):
        name = zone.get("name") or f"ZONA {index + 1}"
        label = name
        if counts.get(_plain(zone.get("name") or ""), 0) > 1:
            label = f"{name} {zone.get('number') or ''}".strip()
        copy = 1
        while _plain(label) in used:
            copy += 1
            label = f"{name} {copy}"
        used.add(_plain(label))
        zone["label"] = label


def _band(rows: list[list[float]], z: float) -> list[tuple]:
    return [(r[0], r[1], r[2], r[3]) for r in rows if r[4] < z < r[5]]


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
    _label_rooms(zones)
    blocking = [row for kind in BLOCKING_TYPES for row in elements.get(kind, [])]
    for zone in zones:
        box = zone["box"]
        if box is None:
            zone["suggested"] = suggest_cameras(zone)
            continue
        z = box["zMin"] + EYE_HEIGHT
        rect = (box["xMin"], box["yMin"], box["xMax"], box["yMax"])
        nested = [
            (o["xMin"], o["yMin"], o["xMax"], o["yMax"])
            for o in (other["box"] for other in zones if other is not zone)
            if o is not None
            and o["zMin"] < z < o["zMax"]
            and _inside(o["xMin"], o["yMin"], rect)
            and _inside(o["xMax"], o["yMax"], rect)
        ]
        zone["suggested"] = suggest_cameras(zone, _band(blocking, z), nested)
        for shot in zone["suggested"].get("shots", []):
            shot["name"] = f"{zone['label']} - {shot['kind']} 01"
            shot["folder"] = zone["label"]
    result: dict[str, Any] = {
        "port": port,
        "zones": zones,
        "element_boxes": elements,
        "box_order": ["xMin", "yMin", "xMax", "yMax", "zMin", "zMax"],
        "note": (
            "Suggested cameras come from room boxes checked against wall and column boxes; "
            "L-shaped rooms and furniture still fool them. Shoot them with shoot_3d_scenes, "
            "look at every image, move or drop the bad ones. Rules: docs/3D_SCENES.md."
        ),
    }
    if truncated:
        result["truncated_types"] = truncated
    return result


async def _addon(client, port, name, parameters=None):
    timeout = (
        SLOW_COMMAND_TIMEOUT
        if name in {"Get3DWindowImage", "Save3DView", "SaveCameraView"}
        else None
    )
    try:
        return await client.own_addon(port, name, parameters, timeout=timeout)
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
        raise ValueError(
            "Each scene name may appear only once per call. Rooms with the same name: use "
            "the zone label from read_scene_model, which adds the zone number."
        )
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
    as_cameras: bool = True,
    camera_path_name: str = DEFAULT_CAMERA_PATH,
    first_camera_number: int = 1,
) -> dict:
    """Save scenes in the View Map under folder_path + each scene's folder.

    Every scene is saved as a 3D view. With as_cameras (the default) each perspective is
    also a camera of the single path camera_path_name, named "<number> <room> - <name>"
    ("3 RECEPÇÃO - 2P 01"). Cameras get no View Map item: in the BIMx Publisher set only
    the path goes in, with "add cameras as separate gallery items" (Vitor, 28/10/2026).
    Dry run first; apply the same inputs with the explicit port and the one-use token.
    """
    entries = _scenes(scenes, MAX_VIEWS)
    if not 1 <= len(folder_path) <= 8 or any(not f or len(f) > 200 for f in folder_path):
        raise ValueError("folder_path needs 1 to 8 folder names of 1 to 200 characters.")
    if not dry_run and port is None:
        raise ValueError("Saving views requires the explicit port of the dry run.")
    port = await resolve_port(client, port)
    if as_cameras and (not camera_path_name or len(camera_path_name) > 200):
        raise ValueError("camera_path_name needs 1 to 200 characters.")
    if type(first_camera_number) is not int or not 1 <= first_camera_number <= 9999:
        raise ValueError("first_camera_number goes from 1 to 9999.")
    plan = [
        {
            "name": s.name,
            "folder_path": folder_path + ([s.folder] if s.folder else []),
            "kind": "camera" if as_cameras and s.parallel is None else "view",
        }
        for s in entries
    ]
    number = first_camera_number
    for scene, row in zip(entries, plan, strict=True):
        if row["kind"] == "camera":
            label = scene.name
            if scene.folder and label.casefold().startswith(f"{scene.folder} - ".casefold()):
                label = label[len(scene.folder) + 3 :]  # "Peso Livre - 1P 01" -> "1P 01"
            room = f"{scene.folder} - " if scene.folder else ""
            row["camera_name"] = f"{number} {room}{label}"
            number += 1
    digest = _digest(
        {
            "port": port,
            "scenes": [s.model_dump() for s in entries],
            "plan": plan,
            "camera_path": camera_path_name if as_cameras else None,
        }
    )
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
            "camera_path": camera_path_name if as_cameras else None,
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
                arguments = {"name": scene.name, "folderPath": row["folder_path"]}
                result = await _addon(client, port, "Save3DView", arguments)
                done = {**row, "status": "saved", "view_guid": result.get("viewGuid")}
                if row["kind"] == "camera":
                    camera = await _addon(
                        client,
                        port,
                        "SaveCameraView",
                        {
                            "name": row["camera_name"],
                            "pathName": camera_path_name,
                            "viewMap": False,
                        },
                    )
                    done["camera_guid"] = camera.get("cameraGuid")
                saved.append(done)
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
            "remove unwanted views by hand. Cameras keep position, target and view cone but "
            "not two-point perspective. The project was not saved."
        ),
    }
