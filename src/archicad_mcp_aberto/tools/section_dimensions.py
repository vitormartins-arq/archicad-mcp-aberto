"""Elements cut in a section and vertical dimensions inside it, through our add-on (addon/).

Tapir's GetSectionElements only lists what a section database already holds, and it comes
back empty for sections that were never generated. Our add-on opens the database of a
section, elevation or interior elevation by its Project Map item, lists every generated
section element with its model parent and its hotspots in the view's own coordinates, and
creates associative linear dimensions there, with witness points on those section elements
(the Archicad 30 API Development Kit, Element_Test, "Do_CreateAssociativeDimensionsOnSection").

In a section view x runs along the cut and y is the height, so a vertical dimension has the
direction (0, 1) and sits at a horizontal station. A witness point names a model element
(slab, finish slab, wall, ceiling) and "top" or "bottom": the hotspot of that element's
section element at the highest or lowest y, the one nearest the station. The dimension stays
linked to the element, so it follows a change of slab thickness or wall height. Display
settings come from a Dimension favorite or the Dimension tool defaults. Never saves.
"""

from __future__ import annotations

import math
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from archicad_mcp_aberto.connection import AddOnError, ArchicadClient, ArchicadError, resolve_port
from archicad_mcp_aberto.tools import hotspot_dimensions, read, solids, write

MAX_DIMENSIONS = 50
MAX_PARENTS = 500
TOLERANCE = 0.001  # metres
NOT_GENERATED = (
    "The view has no section elements yet. Open it once in Archicad (open_navigator_item) or "
    "call again with rebuild=true."
)

_addon = hotspot_dimensions._addon


def _guid(value: str) -> str:
    return str(UUID(value)).upper()


def _hotspot(row: dict) -> dict:
    return {
        "x": row.get("x"),
        "y": row.get("y"),
        "in_index": row.get("inIndex"),
        "suppl_un_id": row.get("supplUnId"),
        "node_type": row.get("nodeType"),
        "sub_type": row.get("subType"),
        "neig_id": row.get("neigId"),
    }


def _range(hotspots: list[dict]) -> dict | None:
    points = [
        (h["x"], h["y"])
        for h in hotspots
        if isinstance(h.get("x"), int | float) and isinstance(h.get("y"), int | float)
    ]
    if not points:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return {"x_min": min(xs), "x_max": max(xs), "y_min": min(ys), "y_max": max(ys)}


async def _cut(client, port, navigator_guid, parents=None, rebuild=False, timeout=None):
    parameters: dict = {"navigatorItemGuid": navigator_guid, "rebuild": rebuild}
    if parents:
        parameters["parentGuids"] = parents
    response = await _addon(client, port, "GetSectionCutElements", parameters, timeout)
    if not isinstance(response.get("elements"), list):
        raise ValueError("Unexpected GetSectionCutElements response.")
    return response


def _group(rows: list[dict]) -> dict[str, dict]:
    """Section elements by model parent, each with its hotspots and their extent."""
    parents: dict[str, dict] = {}
    for row in rows:
        parent = _guid((row.get("parentId") or {}).get("guid", ""))
        hotspots = [_hotspot(h) for h in row.get("hotspots") or []]
        entry = parents.setdefault(
            parent, {"parent_guid": parent, "type": row.get("parentType"), "section_elements": []}
        )
        entry["section_elements"].append(
            {
                "guid": _guid((row.get("sectionElementId") or {}).get("guid", "")),
                "view_extent": _range(hotspots),
                "hotspots": hotspots,
            }
        )
    for entry in parents.values():
        extents = [s["view_extent"] for s in entry["section_elements"] if s["view_extent"]]
        entry["view_y_min"] = min((e["y_min"] for e in extents), default=None)
        entry["view_y_max"] = max((e["y_max"] for e in extents), default=None)
    return parents


async def _model_data(client, port, guids: list[str]) -> dict[str, dict]:
    """Story, layer and the 3D box (absolute Z) of each model parent."""
    out: dict[str, dict] = {g: {} for g in guids}
    step = read.MAX_ELEMENTS_PER_CALL  # GetDetailsOfElements takes at most 100 IDs
    for start in range(0, len(guids), step):
        chunk = guids[start : start + step]
        details = await client.tapir(
            port,
            "GetDetailsOfElements",
            {"elements": read.element_ids(chunk), "fields": write.DETAIL_FIELDS},
        )
        rows = details.get("detailsOfElements")
        if isinstance(rows, list) and len(rows) == len(chunk):
            for guid, row in zip(chunk, rows, strict=True):
                if isinstance(row, dict) and "error" not in row:
                    out[guid].update(
                        floor_index=row.get("floorIndex"), layer_index=row.get("layerIndex")
                    )
        boxes = await read.get_bounding_boxes(client, chunk, port, "3d")
        for row in boxes["boundingBoxes"]:
            if "box" in row:
                out[row["guid"]].update(z_min=row["box"]["zMin"], z_max=row["box"]["zMax"])
    return out


async def get_section_cut_elements(
    client: ArchicadClient,
    navigator_guid: str,
    port: int | None = None,
    parent_guids: list[str] | None = None,
    rebuild: bool = False,
    include_hotspots: bool = True,
) -> dict:
    """List what a section, elevation or interior elevation (its Project Map item GUID) cuts
    or shows, by model element: type, story, layer, absolute z_min/z_max from the 3D box, and
    the section elements with their hotspots and extent in the view (y is the height)."""
    navigator_guid = _guid(navigator_guid)
    parents = [_guid(g) for g in parent_guids or []]
    if len(parents) > MAX_PARENTS:
        raise ValueError(f"Pass at most {MAX_PARENTS} parent GUIDs.")
    port = await resolve_port(client, port)
    response = await _cut(client, port, navigator_guid, parents, rebuild)
    grouped = _group(response["elements"])
    model = await _model_data(client, port, list(grouped)) if grouped else {}
    elements = []
    for guid, entry in grouped.items():
        entry.update(model.get(guid, {}))
        if not include_hotspots:
            for section_element in entry["section_elements"]:
                section_element.pop("hotspots")
        elements.append(entry)
    elements.sort(key=lambda e: (str(e["type"]), -(e.get("z_max") or 0.0)))
    result = {
        "port": port,
        "navigator_guid": navigator_guid,
        "name": response.get("name"),
        "rebuilt": response.get("rebuilt", False),
        "section_element_count": response.get("sectionElementCount", 0),
        "truncated": response.get("truncated", False),
        "elements": elements,
    }
    if not response.get("sectionElementCount"):
        result["note"] = NOT_GENERATED
    return result


class SectionPoint(write.InputModel):
    element_guid: str
    at: Literal["top", "bottom"]
    near_x: float | None = None

    @field_validator("element_guid")
    @classmethod
    def canonical(cls, value: str) -> str:
        return _guid(value)


class SectionDimension(write.InputModel):
    station_x: float
    points: Annotated[list[SectionPoint], Field(min_length=2, max_length=50)]

    @model_validator(mode="after")
    def sound(self) -> SectionDimension:
        if not math.isfinite(self.station_x):
            raise ValueError("station_x must be finite.")
        keys = [(p.element_guid, p.at) for p in self.points]
        if len(set(keys)) != len(keys):
            raise ValueError("A point is repeated.")
        return self


def _pick(point: SectionPoint, entry: dict, station: float, label: str) -> dict:
    """The hotspot at the element's top or bottom in the view, nearest the station."""
    candidates = [
        (section_element["guid"], h)
        for section_element in entry["section_elements"]
        for h in section_element["hotspots"]
        if isinstance(h.get("y"), int | float) and isinstance(h.get("x"), int | float)
    ]
    if not candidates:
        raise ValueError(f"{label}: element {point.element_guid} has no hotspot in this view.")
    extreme = (max if point.at == "top" else min)(h["y"] for _, h in candidates)
    near = station if point.near_x is None else point.near_x
    level = [(g, h) for g, h in candidates if abs(h["y"] - extreme) <= TOLERANCE]
    guid, hotspot = min(level, key=lambda c: abs(c[1]["x"] - near))
    return {
        "element_guid": point.element_guid,
        "element_type": entry.get("type"),
        "at": point.at,
        "section_element_guid": guid,
        "x": hotspot["x"],
        "y": hotspot["y"],
        "witness": {
            "sectionElementId": {"guid": guid},
            "inIndex": hotspot.get("in_index") or 0,
            "supplUnId": hotspot.get("suppl_un_id") or 0,
            "location": {"x": hotspot["x"], "y": hotspot["y"]},
        },
    }


async def _plan(client, plan_input, port, operation):
    navigator_guid, dimensions, favorite = plan_input
    port, target, _ = await write._context(client, port)
    parents = list(dict.fromkeys(p.element_guid for d in dimensions for p in d.points))
    if len(parents) > MAX_PARENTS:
        raise ValueError(f"Pass at most {MAX_PARENTS} different elements.")
    response = await _cut(client, port, navigator_guid, parents)
    if not response.get("sectionElementCount"):
        raise ValueError(NOT_GENERATED)
    grouped = _group(response["elements"])
    settings = None
    if favorite is not None:
        settings = (await _addon(client, port, "GetDimensionFavorite", {"name": favorite}))[
            "settings"
        ]
    items = []
    for i, dimension in enumerate(dimensions):
        label = f"Dimension {i}"
        points = []
        for point in dimension.points:
            entry = grouped.get(point.element_guid)
            if entry is None:
                raise ValueError(
                    f"{label}: element {point.element_guid} is not cut or seen in this view."
                )
            points.append(_pick(point, entry, dimension.station_x, label))
        points.sort(key=lambda p: p["y"])
        for low, high in zip(points, points[1:], strict=False):
            if high["y"] - low["y"] <= TOLERANCE:
                raise ValueError(
                    f"{label}: {low['element_guid']} {low['at']} and {high['element_guid']} "
                    f"{high['at']} are at the same height ({low['y']:.3f})."
                )
        item = {
            "index": i,
            "status": "ready",
            "points": [{k: v for k, v in p.items() if k != "witness"} for p in points],
            "segments_m": [
                round(b["y"] - a["y"], 4) for a, b in zip(points, points[1:], strict=False)
            ],
            "parameters": {
                "referencePoint": {"x": dimension.station_x, "y": points[0]["y"]},
                "direction": {"x": 0.0, "y": 1.0},
                "witnessPoints": [p["witness"] for p in points],
            },
        }
        if favorite is not None:
            item.update(favorite=favorite, favorite_settings=settings)
        items.append(item)
    return {
        "operation": operation,
        "target": target,
        "navigator_guid": navigator_guid,
        "view_name": response.get("name"),
        "items": items,
    }


def _mismatches(item: dict, row: dict) -> list[str]:
    wanted = item["parameters"]["witnessPoints"]
    found = row.get("witnessPoints")
    if not isinstance(found, list) or len(found) != len(wanted):
        return ["witnessPoints"]
    problems = []
    for n, (want, got) in enumerate(zip(wanted, found, strict=True)):
        guid = str((got.get("elementId") or {}).get("guid", "")).upper()
        if guid != want["sectionElementId"]["guid"]:
            problems.append(f"witnessPoints.{n}.elementId")
        at = got.get("location") or {}
        if (
            not isinstance(at.get("y"), int | float)
            or abs(at["y"] - want["location"]["y"]) > TOLERANCE
        ):
            problems.append(f"witnessPoints.{n}.location.y")
    if "favorite_settings" in item:
        settings = row.get("settings") or {}
        for path in hotspot_dimensions.COMPARED_SETTINGS:
            ours = hotspot_dimensions._setting(settings, path)
            theirs = hotspot_dimensions._setting(item["favorite_settings"], path)
            if not hotspot_dimensions._same(ours, theirs):
                problems.append(f"settings.{path}")
    problems.extend(row.get("textDifferences") or [])
    return problems


async def _dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    receipt["undo_scope"] = "The whole batch is one Undo step (Create Section Dimensions)."
    parameters = {
        "navigatorItemGuid": receipt["navigator_guid"],
        "dimensions": [i["parameters"] for i in items],
    }
    if "favorite" in items[0]:
        parameters["favorite"] = items[0]["favorite"]
    try:
        raw = await _addon(
            client, port, "CreateSectionDimensions", parameters, receipt["write_timeout_seconds"]
        )
    except AddOnError as exc:
        for item in items:
            item.update(status="failed", error=exc.detail or str(exc))
        return
    except ArchicadError as exc:
        return solids._unknown(receipt, f"CreateSectionDimensions: {exc}")
    rows = raw.get("elements")
    if not isinstance(rows, list) or len(rows) != len(items):
        return solids._unknown(receipt, "Unexpected CreateSectionDimensions response.")
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


async def create_section_dimensions(
    client: ArchicadClient,
    navigator_guid: str,
    dimensions: list[dict | SectionDimension],
    favorite: str | None = None,
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 50 vertical associative dimensions inside one section, elevation
    or interior elevation (its Project Map item GUID). Each sits at station_x and measures
    points [{element_guid, at: top|bottom, near_x?}] on model elements the view cuts. One
    Dimension favorite or the tool defaults. One Undo step; never saves."""
    if not 1 <= len(dimensions) <= MAX_DIMENSIONS:
        raise ValueError(f"Pass between 1 and {MAX_DIMENSIONS} dimensions.")
    validated = [
        d if isinstance(d, SectionDimension) else SectionDimension.model_validate(d)
        for d in dimensions
    ]
    return await write._write(
        client,
        (_guid(navigator_guid), validated, favorite),
        port,
        dry_run,
        confirmation_token,
        "create_section_dimensions",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
