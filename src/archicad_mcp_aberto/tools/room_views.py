"""Room enlargement views: one floor plan view per room, saved in the View Map.

save_room_plan_views reads the zones (name, number, story, plan box) and, for each room,
saves its story's floor plan as a View Map view framed on the room plus a margin, with
an optional drawing scale and layer combination. Each view goes into folder_path plus a
folder named after the room, and the views are numbered in order (story, then zone
number): "AMP 01 - BANHO SOCIAL", "AMP 02 - COZINHA" and so on.

It uses the ArchicadMcpAberto add-on (addon/, SaveStoryView). Dry run first; apply the
same inputs with the explicit port and the one-use token. View Map changes are outside
Archicad's Undo, and the project is never saved.
"""

from __future__ import annotations

import re
import time
from typing import Any
from uuid import uuid4
from weakref import WeakKeyDictionary

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError, resolve_port
from archicad_mcp_aberto.tools import drafting, read, scenes
from archicad_mcp_aberto.tools.write import PREVIEW_SECONDS, _digest

MAX_VIEWS = 60
TOLERANCE = 1e-3  # metres

_previews: WeakKeyDictionary[ArchicadClient, dict[str, tuple[float, str]]] = WeakKeyDictionary()


def _number_key(number: Any) -> tuple:
    """Zone numbers in natural order: 2 before 10, text after numbers."""
    parts = re.findall(r"\d+|\D+", str(number or ""))
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p.casefold()) for p in parts)


async def _rooms(client, port) -> list[dict]:
    zones = await scenes._zones(client, port)
    if not zones:
        return []
    raw = await client.tapir(
        port,
        "GetDetailsOfElements",
        {"elements": read.element_ids([z["guid"] for z in zones]), "fields": ["floorIndex"]},
    )
    rows = raw.get("detailsOfElements")
    if not isinstance(rows, list) or len(rows) != len(zones):
        raise ValueError("Unexpected zone details response.")
    for zone, row in zip(zones, rows, strict=True):
        floor = row.get("floorIndex") if isinstance(row, dict) else None
        zone["story_index"] = floor if isinstance(floor, int) else None
    scenes._label_rooms(zones)
    return zones


def _wanted(zones: list[dict], rooms: list[str] | None, stories: list[int] | None) -> list[dict]:
    picked = [z for z in zones if stories is None or z["story_index"] in stories]
    if rooms is None:
        return picked
    out = []
    for wanted in rooms:
        key = scenes._plain(wanted).strip()
        found = [
            z
            for z in picked
            if key in {scenes._plain(z["label"]), scenes._plain(z.get("name") or "")}
            or (z.get("number") and key == scenes._plain(str(z["number"])))
        ]
        if not found:
            raise ValueError(f"No room {wanted!r} on the chosen stories.")
        out.extend(z for z in found if z not in out)
    return out


def _plan(zones: list[dict], args: dict, story_names: dict[int, str]) -> list[dict]:
    zones = sorted(
        zones,
        key=lambda z: (z["story_index"], _number_key(z.get("number")), scenes._plain(z["label"])),
    )
    width = max(2, len(str(args["first_number"] + len(zones) - 1)))
    plan = []
    for offset, zone in enumerate(zones):
        number = str(args["first_number"] + offset).zfill(width)
        box = zone["box"]
        margin = args["margin"]
        view = {
            "name": f"{args['prefix']} {number} - {zone['label']}".strip(),
            "folder_path": [*args["folder_path"], zone["label"]],
            "room": zone["label"],
            "zone_guid": zone["guid"],
            "story_index": zone["story_index"],
            "story": story_names.get(zone["story_index"]),
            "zoom": {
                "xMin": round(box["xMin"] - margin, 3),
                "yMin": round(box["yMin"] - margin, 3),
                "xMax": round(box["xMax"] + margin, 3),
                "yMax": round(box["yMax"] + margin, 3),
            },
        }
        if args["scale"] is not None:
            view["drawing_scale"] = args["scale"]
        if args["layer_combination"] is not None:
            view["layer_combination"] = args["layer_combination"]
        plan.append(view)
    return plan


def _mismatches(view: dict, saved: Any) -> list[str]:
    if not isinstance(saved, dict):
        return ["view"]
    problems = []
    zoom = saved.get("zoom")
    if (
        not saved.get("saveZoom")
        or not isinstance(zoom, dict)
        or any(
            not isinstance(zoom.get(k), int | float) or abs(zoom[k] - v) > TOLERANCE
            for k, v in view["zoom"].items()
        )
    ):
        problems.append("zoom")
    if "drawing_scale" in view and (
        not saved.get("saveDrawingScale") or saved.get("drawingScale") != view["drawing_scale"]
    ):
        problems.append("drawing_scale")
    if "layer_combination" in view and (
        not saved.get("saveLayers") or saved.get("layerCombination") != view["layer_combination"]
    ):
        problems.append("layer_combination")
    return problems


async def save_room_plan_views(
    client: ArchicadClient,
    folder_path: list[str],
    rooms: list[str] | None = None,
    stories: list[int] | None = None,
    prefix: str = "AMP",
    first_number: int = 1,
    margin: float = 0.5,
    scale: int | None = 25,
    layer_combination: str | None = None,
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/save one framed floor plan view per room, in a folder named after it."""
    if not 1 <= len(folder_path) <= 8 or any(not f or len(f) > 200 for f in folder_path):
        raise ValueError("folder_path needs 1 to 8 folder names of 1 to 200 characters.")
    if len(prefix) > 40 or prefix != prefix.strip():
        raise ValueError("prefix takes up to 40 characters, without outer spaces.")
    if type(first_number) is not int or not 1 <= first_number <= 9999:
        raise ValueError("first_number goes from 1 to 9999.")
    if not isinstance(margin, int | float) or not 0 <= margin <= 10:
        raise ValueError("margin goes from 0 to 10 metres.")
    if scale is not None and (type(scale) is not int or not 1 <= scale <= 100000):
        raise ValueError("scale is the denominator, 25 for 1:25.")
    if rooms is not None and not 1 <= len(rooms) <= MAX_VIEWS:
        raise ValueError(f"Pass between 1 and {MAX_VIEWS} rooms, or leave rooms out.")
    if not dry_run and port is None:
        raise ValueError("Saving views requires the explicit port of the dry run.")
    port = await resolve_port(client, port)
    args = {
        "folder_path": list(folder_path),
        "rooms": rooms,
        "stories": stories,
        "prefix": prefix,
        "first_number": first_number,
        "margin": float(margin),
        "scale": scale,
        "layer_combination": layer_combination,
    }
    story_rows = (await client.tapir(port, "GetStories")).get("stories", [])
    story_names = {s["index"]: s.get("name") for s in story_rows if isinstance(s, dict)}
    if stories is not None and (missing := sorted(set(stories) - set(story_names))):
        raise ValueError(f"Stories {missing} do not exist.")
    if layer_combination is not None:
        combos = await drafting._attributes(client, port, "LayerCombination")
        args["layer_combination"] = drafting._named(combos, layer_combination, "Layer combination")[
            "name"
        ]
    zones = [z for z in await _rooms(client, port) if z["box"] and z["story_index"] is not None]
    plan = _plan(_wanted(zones, rooms, stories), args, story_names)
    if not plan:
        raise ValueError("No zone with a story and a plan box was found.")
    if len(plan) > MAX_VIEWS:
        raise ValueError(f"{len(plan)} rooms; save at most {MAX_VIEWS} at a time (pick stories).")
    digest = _digest({"port": port, "args": args, "plan": plan})
    previews = _previews.setdefault(client, {})
    now = time.monotonic()
    for token in [t for t, (expiry, _) in previews.items() if expiry <= now]:
        previews.pop(token)
    if dry_run:
        await scenes._addon(client, port, "Get3DCamera")  # fails early without the add-on
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
        raise ValueError("Rooms, settings or port changed since the preview. Run a new dry run.")
    saved = []
    for view in plan:
        payload: dict[str, Any] = {
            "storyIndex": view["story_index"],
            "name": view["name"],
            "folderPath": view["folder_path"],
            "zoom": view["zoom"],
        }
        if "drawing_scale" in view:
            payload["drawingScale"] = view["drawing_scale"]
        if "layer_combination" in view:
            payload["layerCombination"] = view["layer_combination"]
        try:
            result = await scenes._addon(client, port, "SaveStoryView", payload)
        except ArchicadError as exc:
            saved.append({**view, "status": "failed", "error": str(exc)})
            continue
        row = {**view, "view_guid": result.get("viewGuid"), "after": result.get("view")}
        problems = _mismatches(view, result.get("view"))
        row["status"] = "verification_failed" if problems else "verified"
        if problems:
            row["mismatches"] = problems
        saved.append(row)
    return {
        "port": port,
        "dry_run": False,
        "views": saved,
        "saved": sum(v["status"] != "failed" for v in saved),
        "note": (
            "New views appear at the top of their folder. View Map changes are outside Undo; "
            "remove unwanted views by hand. The project was not saved."
        ),
    }
