"""Small, reviewable writes: create walls, slabs, columns and objects, move, set properties.

Lengths are metres; no project is ever saved.

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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError, resolve_port
from archicad_mcp_aberto.tools.read import _library_inventory, element_ids, get_bounding_boxes

Positive = Annotated[float, Field(gt=0)]
MAX_WALLS = 20
MAX_SLABS = 20
MAX_COLUMNS = 20
MAX_OBJECTS = 20
MAX_MOVES = 50
MAX_PROPERTY_CHANGES = 100
MOVE_TOLERANCE = 0.001  # metres; bounding boxes are compared after a move
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


class BeamCreate(InputModel):
    start: Point
    end: Point
    floor_index: int
    level: float
    width: Positive
    height: Positive

    @model_validator(mode="after")
    def nonzero_length(self) -> BeamCreate:
        if math.hypot(self.start.x - self.end.x, self.start.y - self.end.y) < 1e-6:
            raise ValueError("A beam must be at least 0.000001 m long.")
        return self


class ColumnCreate(InputModel):
    origin: Point
    floor_index: int
    height: Positive
    base_level: float
    section: Literal["rectangular", "circular"] = "rectangular"
    width: Positive | None = None
    depth: Positive | None = None
    diameter: Positive | None = None

    @model_validator(mode="after")
    def valid_section(self) -> ColumnCreate:
        if self.section == "rectangular":
            if self.width is None or self.depth is None or self.diameter is not None:
                raise ValueError("Rectangular columns require width/depth and no diameter.")
        elif self.diameter is None or self.width is not None or self.depth is not None:
            raise ValueError("Circular columns require diameter and no width/depth.")
        return self


class ObjectCreate(InputModel):
    library_part_name: Annotated[str, Field(min_length=1, max_length=255)]
    origin: Point
    floor_index: int
    base_level: float
    angle: float = 0.0

    @field_validator("library_part_name")
    @classmethod
    def visible_name(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("library_part_name must not start or end with spaces.")
        return value


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


class ZoneCreate(InputModel):
    outline: Annotated[list[Point], Field(min_length=3, max_length=200)]
    name: Annotated[str, Field(min_length=1)]
    number: Annotated[str, Field(min_length=1)]
    floor_index: int

    @model_validator(mode="after")
    def valid_polygon(self) -> ZoneCreate:
        if not self.name.strip() or not self.number.strip():
            raise ValueError("Zone name and number must not be blank.")
        # Reuse the exact slab polygon validator, including closure normalization.
        polygon = SlabCreate(
            outline=self.outline, floor_index=self.floor_index, thickness=1.0, level=0.0
        )
        self.outline = polygon.outline
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


# operation -> (noun used in messages, per-item receipt key, note shown with a preview)
OPERATIONS = {
    "create_windows": (
        "window",
        "window_receipt_id",
        "Each window goes into an existing wall; the Window tool default or the named "
        "favorite decides the library part.",
    ),
    "create_doors": (
        "door",
        "door_receipt_id",
        "Each door goes into an existing wall; the Door tool default or the named "
        "favorite decides the library part.",
    ),
    "modify_walls": ("wall edit", "wall_edit_receipt_id", "Only requested fields are modified."),
    "modify_slabs": ("slab edit", "slab_edit_receipt_id", "Only requested fields are modified."),
    "modify_columns": (
        "column edit",
        "column_edit_receipt_id",
        "Only requested fields are modified.",
    ),
    "modify_beams": ("beam edit", "beam_edit_receipt_id", "Only requested fields are modified."),
    "modify_windows": (
        "window edit",
        "window_edit_receipt_id",
        "Only requested fields are modified.",
    ),
    "modify_doors": ("door edit", "door_edit_receipt_id", "Only requested fields are modified."),
    "modify_roofs": ("roof edit", "roof_edit_receipt_id", "Only requested fields are modified."),
    "modify_texts": ("text edit", "text_edit_receipt_id", "Only requested fields are modified."),
    "modify_objects": (
        "object edit",
        "object_edit_receipt_id",
        "Only requested fields are modified.",
    ),
    "set_gdl_parameters": ("GDL change", "gdl_receipt_id", "Existing scalar parameters only."),
    "rotate_elements": (
        "rotation",
        "rotation_receipt_id",
        "Rotate without copying; verify geometry.",
    ),
    "create_zones": ("zone", "zone_receipt_id", "New zones inherit category/stamp defaults."),
    "create_beams": ("beam", "beam_receipt_id", "New beams inherit layer/material defaults."),
    "create_roofs": (
        "roof",
        "roof_receipt_id",
        "New roofs inherit the Roof tool's layer and building material.",
    ),
    "create_texts": (
        "text",
        "text_receipt_id",
        "New texts take font and style from the Text tool default.",
    ),
    "delete_elements": (
        "deletion",
        "delete_receipt_id",
        "Only editable elements in an untitled test project can be deleted. Never saves.",
    ),
    "create_walls": (
        "wall",
        "wall_receipt_id",
        "New walls inherit Archicad's default layer and building material.",
    ),
    "create_slabs": (
        "slab",
        "slab_receipt_id",
        "New slabs inherit Archicad's default layer and building material.",
    ),
    "create_columns": (
        "column",
        "column_receipt_id",
        "New columns inherit Archicad's default layer and building material.",
    ),
    "create_objects": (
        "object",
        "object_receipt_id",
        "New objects keep the library part's default size and the Object tool's layer. "
        "A library part name Archicad cannot find fails only that object.",
    ),
    "move_elements": (
        "move",
        "move_receipt_id",
        "Each element moves by its vector; boxes are checked after.",
    ),
    "set_property_values": (
        "property change",
        "change_receipt_id",
        "Each value is written as shown and read back after.",
    ),
    "set_classifications": (
        "classification change",
        "classification_receipt_id",
        "Each classification is written as shown and read back after.",
    ),
    "create_lines": ("line", "line_receipt_id", "New lines take line type from the Line tool."),
    "create_polylines": (
        "polyline",
        "polyline_receipt_id",
        "New polylines take line type from the Polyline tool.",
    ),
    "create_splines": (
        "spline",
        "spline_receipt_id",
        "New splines are auto-smoothed and take line type from the Spline tool.",
    ),
    "create_arcs": ("arc", "arc_receipt_id", "New arcs take line type from the Arc tool."),
    "create_circles": ("circle", "circle_receipt_id", "New circles take line type from the tool."),
    "create_fills": (
        "fill",
        "fill_receipt_id",
        "New fills keep the Fill tool's settings unless named here.",
    ),
    "create_layers": (
        "layer",
        "layer_receipt_id",
        "New layers are added; an existing name is never overwritten.",
    ),
    "set_element_layers": (
        "layer change",
        "layer_change_receipt_id",
        "Each element moves to its layer and is read back after.",
    ),
    "create_groups": (
        "group",
        "group_receipt_id",
        "Each new group is read back; ungroup in Archicad to undo.",
    ),
    "set_project_info_fields": (
        "project info change",
        "project_info_receipt_id",
        "Each field is written as shown and read back after.",
    ),
    "apply_favorites": (
        "favorite application",
        "favorite_receipt_id",
        "Favorites change settings, never geometry; check the result in Archicad.",
    ),
    "create_labels": (
        "label",
        "label_receipt_id",
        "New labels take font and style from the Label tool default.",
    ),
    "lock_elements": (
        "lock",
        "lock_receipt_id",
        "Manual lock (Edit > Locking), not Teamwork; each element's editability is read back.",
    ),
    "unlock_elements": (
        "unlock",
        "unlock_receipt_id",
        "Manual unlock, not Teamwork; each element's editability is read back.",
    ),
    "update_zones": (
        "zone update",
        "zone_update_receipt_id",
        "Recalculates every zone of the project; check areas and stamps in Archicad.",
    ),
    "create_property_groups": (
        "property group",
        "property_group_receipt_id",
        "New custom groups are added; an existing group name is never changed.",
    ),
    "create_properties": (
        "property",
        "property_receipt_id",
        "New custom properties are added; existing properties are never changed.",
    ),
    "create_worksheets": (
        "worksheet",
        "worksheet_receipt_id",
        "New empty independent worksheets go to the Project Map.",
    ),
    "create_details": (
        "detail",
        "detail_receipt_id",
        "New empty independent details go to the Project Map.",
    ),
    "create_layouts": (
        "layout",
        "layout_receipt_id",
        "New layouts take size and margins from their existing master layout.",
    ),
    "rename_items": (
        "rename",
        "rename_receipt_id",
        "Each item keeps its GUID, so elements that use it follow the new name. "
        "Check the list before applying.",
    ),
}
OPERATIONS["modify_labels"] = (
    "label edit",
    "label_edit_receipt_id",
    "Text and height_mm only; position is preserved. "
    "Native edits may flatten rich text and disable word wrap.",
)

OPERATIONS["create_issues"] = (
    "issue",
    "issue_receipt_id",
    "Creates issue metadata only; does not save or export BCF.",
)
OPERATIONS["attach_elements_to_issue"] = (
    "issue attachment",
    "issue_attachment_receipt_id",
    "Associates existing elements as Highlight only.",
)

OPERATIONS["create_meshes"] = (
    "mesh",
    "mesh_receipt_id",
    "Absolute project metres; simple terrain boundary, no holes/contours.",
)
OPERATIONS["modify_meshes"] = (
    "mesh edit",
    "mesh_edit_receipt_id",
    "Only level/skirt/display change; topology is preserved.",
)

OPERATIONS["set_view_settings"] = (
    "view settings",
    "view_settings_receipt_id",
    "No guaranteed Navigator Undo. Previous values are retained; restore by a new preview/apply.",
)

OPERATIONS["set_layer_settings"] = (
    "layer settings",
    "layer_settings_receipt_id",
    "Existing layer flags only. Current visibility/editability can change; no guaranteed Undo.",
)

OPERATIONS["create_sections"] = (
    "section",
    "section_receipt_id",
    "New sections take the Section tool's marker and settings; Archicad numbers the ID.",
)


# operation -> (Tapir create command, list key in its parameters)
CREATE_COMMANDS = {
    "create_windows": ("CreateWindows", "windowsData"),
    "create_doors": ("CreateDoors", "doorsData"),
    "create_zones": ("CreateZones", "zonesData"),
    "create_beams": ("CreateBeams", "beamsData"),
    "create_walls": ("CreateWalls", "wallsData"),
    "create_slabs": ("CreateSlabs", "slabsData"),
    "create_columns": ("CreateColumns", "columnsData"),
    "create_objects": ("CreateObjects", "objectsData"),
    "create_roofs": ("CreateRoofs", "roofsData"),
    "create_texts": ("CreateTexts", "textsData"),
    "create_labels": ("CreateLabels", "labelsData"),
    "create_lines": ("CreateLineElements", "linesData"),
    "create_polylines": ("CreatePolylines", "polylinesData"),
    "create_splines": ("CreateSplines", "splinesData"),
    "create_arcs": ("CreateArcs", "arcsData"),
    "create_circles": ("CreateCircles", "circlesData"),
    "create_fills": ("CreateHatches", "hatchesData"),
}
CREATE_COMMANDS["create_meshes"] = ("CreateMeshes", "meshesData")
CREATE_COMMANDS["create_sections"] = ("CreateSections", "sectionsData")
OPERATIONS["create_keynote_folders"] = (
    "keynote folder",
    "keynote_receipt_id",
    "New keynote folders only; existing keys are never changed.",
)
OPERATIONS["create_keynote_items"] = (
    "keynote item",
    "keynote_receipt_id",
    "New keynote items only; existing keys are never changed.",
)
OPERATIONS["create_interior_elevations"] = (
    "interior elevation",
    "interior_elevation_receipt_id",
    "New interior elevations take the Interior Elevation tool's marker and settings.",
)
CREATE_COMMANDS["create_interior_elevations"] = (
    "CreateInteriorElevations",
    "interiorElevationsData",
)
OPERATIONS["set_attribute_property_values"] = (
    "attribute property change",
    "attribute_property_receipt_id",
    "Values are display text converted by Archicad; each is read back as text.",
)
OPERATIONS["create_favorites_from_elements"] = (
    "favorite",
    "favorite_receipt_id",
    "Each new favorite copies its element's settings; existing favorites are never changed.",
)
OPERATIONS["create_morphs"] = (
    "morph",
    "morph_receipt_id",
    "Axis-aligned closed solid boxes in absolute project metres; Morph tool defaults for "
    "the rest. A morph on a story that is not shown in Archicad makes Archicad open a "
    "dialog that blocks the API until someone clicks it; show that story first.",
)
CREATE_COMMANDS["create_morphs"] = ("CreateMorphs", "morphsData")
OPERATIONS["create_wall_thickness_dimensions"] = (
    "wall thickness dimension",
    "dimension_receipt_id",
    "Associative dimension of both wall faces; Dimension tool defaults for display.",
)
CREATE_COMMANDS["create_wall_thickness_dimensions"] = (
    "CreateWallThicknessDimensions",
    "dimensionsData",
)
OPERATIONS["create_openings"] = (
    "opening",
    "opening_receipt_id",
    "Rectangular Opening-tool openings in existing walls or slabs; tool defaults for the rest.",
)
CREATE_COMMANDS["create_openings"] = ("CreateOpenings", "openingsData")


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


async def _guard_sequential_context(client: ArchicadClient, receipt: dict, index: int) -> bool:
    """Reconfirm the preview target before a later command in a sequential batch."""
    if index == 0:
        return True
    target = receipt["target"]
    try:
        _, current, _ = await _context(client, target["port"])
        expected = {key: target[key] for key in current}
        if current == expected:
            return True
        error = "Target context changed between batch items; run a new preview."
    except (ArchicadError, KeyError, TypeError, ValueError) as exc:
        error = f"Could not re-confirm target context between batch items: {exc}"
    receipt["context_error"] = error
    for item in receipt["items"][index:]:
        item.update(status="failed", not_attempted=True, error=error)
    return False


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
    column = operation == "create_columns"
    zone = operation == "create_zones"
    beam = operation == "create_beams"
    obj = operation == "create_objects"
    kind = (
        "Beam" if beam else "Object" if obj else "Column" if column else "Slab" if slab else "Wall"
    )
    if zone:
        kind = "Zone"
    library_parts = {}
    if obj:
        inventory = await _library_inventory(client, port)
        for row in inventory["libraryParts"]:
            if row["typeId"] == "Object":
                library_parts.setdefault(row["documentName"].casefold(), []).append(row)
        for wall in walls:
            candidates = library_parts.get(wall.library_part_name.casefold(), [])
            if not candidates:
                if inventory["skippedCount"] > 0:
                    continue  # An unreadable part may still resolve during CreateObjects.
                raise ValueError(
                    f"Library part {wall.library_part_name!r}: "
                    "name not in loaded Object library parts."
                )
            if len({row["guid"].upper() for row in candidates}) != 1:
                raise ValueError(f"Ambiguous library part name {wall.library_part_name!r}.")
    for index, wall in enumerate(walls):
        if wall.floor_index not in floors:
            raise ValueError(f"{kind} {index}: story {wall.floor_index} does not exist.")
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
            else _column_payload(wall)
            if column
            else _object_payload(wall)
            if obj
            else _beam_payload(wall)
            if beam
            else _zone_payload(wall)
            if zone
            else _create_payload(wall)
        )
        item = {"index": index, "status": "ready", "parameters": payload}
        if obj:
            candidates = library_parts.get(wall.library_part_name.casefold(), [])
            if candidates:
                item["library_part_guid"] = candidates[0]["guid"].upper()
            else:
                item.update(
                    status="unconfirmed",
                    warning="Library inventory is partial; this name could not be confirmed. "
                    "CreateObjects resolves it at apply and reports any error for this item.",
                )
        items.append(item)
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
            if math.isclose(expected, actual, rel_tol=0.0, abs_tol=1e-7):
                return []
        return [path]
    return [] if expected == actual else [path]


async def _dispatch(client: ArchicadClient, receipt: dict, mismatch=None) -> None:
    items, port = receipt["items"], receipt["target"]["port"]
    slab = receipt["operation"] == "create_slabs"
    column = receipt["operation"] == "create_columns"
    zone = receipt["operation"] == "create_zones"
    beam = receipt["operation"] == "create_beams"
    obj = receipt["operation"] == "create_objects"
    command, key = CREATE_COMMANDS[receipt["operation"]]
    try:
        raw = await client.tapir(
            port,
            command,
            {key: [i["parameters"] for i in items]},
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
                mismatch(item, row)
                if mismatch
                else _slab_mismatches(item, row, receipt["target"])
                if slab
                else _column_mismatches(item, row, receipt["target"])
                if column
                else _object_mismatches(item, row)
                if obj
                else _beam_mismatches(item, row, receipt["target"])
                if beam
                else _zone_mismatches(item, row)
                if zone
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
    *,
    planner_override=None,
    dispatcher_override=None,
) -> dict:
    if client.session_id is None:
        raise RuntimeError("ArchicadClient must be used inside 'async with'.")
    state = _states.get(client)
    if state is None or state.session_id != client.session_id:
        state = WriteState(session_id=client.session_id)
        _states[client] = state
    kind, receipt_key, preview_note = OPERATIONS[operation]
    planner = planner_override or {
        "move_elements": _move_plan,
        "set_property_values": _property_plan,
        "delete_elements": _delete_plan,
    }.get(operation, _plan)
    async with state.lock:
        if dry_run:
            plan = await planner(client, walls, port, operation)
            await _preview_names(client, plan)
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
                + preview_note,
            }
        if port is None:
            raise ValueError(f"Applying a {kind} plan requires its explicit port.")
        entry = state.previews.get(confirmation_token or "")
        if entry is None or entry[0] <= time.monotonic():
            raise ValueError("Preview missing, expired or already consumed. Run a new dry run.")
        plan = await planner(client, walls, port, operation)
        await _preview_names(client, plan)
        if _plan_digest(plan) != _plan_digest(entry[1]):
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
            item[receipt_key] = str(uuid4())
        receipt["prepared_receipt_path"] = _journal(receipt, "prepared")
        # Consume before dispatch, including if dispatch or verification later fails.
        state.previews.pop(confirmation_token)
        dispatcher = dispatcher_override or {
            "move_elements": _move_dispatch,
            "delete_elements": _delete_dispatch,
            "set_property_values": _property_dispatch,
        }.get(operation, _dispatch)
        await dispatcher(client, receipt)
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
        if receipt.get("revert_note"):
            receipt["note"] = "No project was saved. " + receipt["revert_note"]

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


def _same_polygon(wanted: list, outline: Any) -> bool:
    """Same vertices in any starting point or direction; a closing repeat is ignored."""
    if isinstance(outline, list) and len(outline) > 1 and not _mismatches(outline[0], outline[-1]):
        outline = outline[:-1]
    if not isinstance(outline, list) or len(outline) != len(wanted):
        return False
    for sequence in (outline, list(reversed(outline))):
        for shift in range(len(sequence)):
            rotated = sequence[shift:] + sequence[:shift]
            if all(not _mismatches(a, b) for a, b in zip(wanted, rotated, strict=True)):
                return True
    return False


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
    if not _same_polygon(p["polygonCoordinates"], details.get("polygonOutline")):
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


def _column_payload(column: ColumnCreate) -> dict:
    circular = column.section == "circular"
    return {
        "coordinates": {**column.origin.model_dump(), "z": column.base_level},
        "floorIndex": column.floor_index,
        "height": column.height,
        "width": column.diameter if circular else column.width,
        "depth": column.diameter if circular else column.depth,
        "circleBased": circular,
        "isWidthAndHeightLinked": circular,
        "axisRotationAngle": 0.0,
        "coreAnchor": "Center",
    }


def _column_mismatches(item: dict, row: Any, target: dict) -> list[str]:
    p = item["parameters"]
    coords = p["coordinates"]
    story = next(s for s in target["stories"] if s["index"] == p["floorIndex"])
    expected = {
        "type": "Column",
        "floorIndex": p["floorIndex"],
        "details": {
            "origin": {"x": coords["x"], "y": coords["y"]},
            "height": p["height"],
            "zCoordinate": coords["z"],
            "bottomOffset": coords["z"] - story["level"],
            "axisRotationAngle": 0.0,
            "coreAnchor": "Center",
            "isSlanted": False,
            "width": p["width"],
            "depth": p["depth"],
            "circleBased": p["circleBased"],
            "isWidthAndHeightLinked": p["circleBased"],
        },
    }
    differences = _mismatches(expected, row)
    details = row.get("details") if isinstance(row, dict) else None
    if isinstance(details, dict) and "profileId" in details:
        differences.append("details.profileId")
    return differences


async def create_columns(
    client: ArchicadClient,
    columns: list[dict | ColumnCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 straight columns. Metres; base_level is absolute project Z.

    Rectangular width/depth or circular diameter; centered, unrotated core.
    Layer/material and other defaults inherit the Column tool; incompatible defaults
    are reported by verification. Shares the wall/slab token, receipt and timeout policy.
    """
    if not 1 <= len(columns) <= MAX_COLUMNS:
        raise ValueError(f"Pass between 1 and {MAX_COLUMNS} columns.")
    validated = [
        c if isinstance(c, ColumnCreate) else ColumnCreate.model_validate(c) for c in columns
    ]
    return await _write(client, validated, port, dry_run, confirmation_token, "create_columns")


def _object_payload(obj: ObjectCreate) -> dict:
    return {
        "libraryPartName": obj.library_part_name,
        "coordinates": {**obj.origin.model_dump(), "z": obj.base_level},
        "floorIndex": obj.floor_index,
        "angle": obj.angle,
    }


def _object_mismatches(item: dict, row: Any) -> list[str]:
    p = item["parameters"]
    expected = {
        "type": "Object",
        "floorIndex": p["floorIndex"],
        "details": {"origin": p["coordinates"]},
    }
    differences = _mismatches(expected, row)
    details = row.get("details") if isinstance(row, dict) else None
    details = details if isinstance(details, dict) else {}
    angle = details.get("angle")
    if not isinstance(angle, (float, int)) or isinstance(angle, bool):
        differences.append("details.angle")
    else:
        # Archicad may store the angle in another turn; compare on the circle.
        turn = (angle - p["angle"]) % math.tau
        if min(turn, math.tau - turn) > 1e-7:
            differences.append("details.angle")
    library_part = details.get("libPart")
    name = library_part.get("name") if isinstance(library_part, dict) else None
    if not isinstance(name, str) or name.casefold() != p["libraryPartName"].casefold():
        differences.append("details.libPart.name")
    return differences


async def create_objects(
    client: ArchicadClient,
    objects: list[dict | ObjectCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 library part objects by name. Metres, radians.

    base_level is absolute project Z. Size and parameters stay the library part's
    defaults; layer and pens inherit the Object tool. A name Archicad cannot find
    fails only that object. Shares the token, receipt and timeout policy.
    """
    if not 1 <= len(objects) <= MAX_OBJECTS:
        raise ValueError(f"Pass between 1 and {MAX_OBJECTS} objects.")
    validated = [
        o if isinstance(o, ObjectCreate) else ObjectCreate.model_validate(o) for o in objects
    ]
    return await _write(client, validated, port, dry_run, confirmation_token, "create_objects")


class Vector(InputModel):
    x: float
    y: float
    z: float = 0.0


class ElementMove(InputModel):
    guid: str
    vector: Vector

    @field_validator("guid")
    @classmethod
    def canonical_guid(cls, value: str) -> str:
        return str(UUID(value)).upper()

    @model_validator(mode="after")
    def real_move(self) -> ElementMove:
        v = self.vector
        length = math.sqrt(v.x * v.x + v.y * v.y + v.z * v.z)
        if length < MOVE_TOLERANCE:
            raise ValueError("A move vector must be at least 1 mm long.")
        if length > 10_000:
            raise ValueError("A move vector must be at most 10 km long.")
        return self


async def _boxes(client: ArchicadClient, port: int, guids: list[str]) -> dict[str, dict]:
    """2D and 3D boxes per GUID; a missing box (2D-only element, say) stays out."""
    out: dict[str, dict] = {g: {} for g in guids}
    for mode in ("2d", "3d"):
        result = await get_bounding_boxes(client, guids, port, mode)
        for row in result["boundingBoxes"]:
            if "box" in row:
                out[row["guid"]][mode] = row["box"]
    return out


async def _move_plan(
    client: ArchicadClient, moves: list[ElementMove], port: int | None, operation: str
) -> dict:
    port, target, _ = await _context(client, port)
    guids = [m.guid for m in moves]
    everything = await client.command(port, "GetAllElements")
    existing = {e["elementId"]["guid"].upper() for e in everything["elements"]}
    missing = [g for g in guids if g not in existing]
    if missing:
        raise ValueError(f"Not in this project: {', '.join(missing)}.")
    details = await client.tapir(
        port,
        "GetDetailsOfElements",
        {
            "elements": element_ids(guids),
            "fields": ["type", "floorIndex", "layerIndex", "hotlinkId"],
        },
    )
    rows = details.get("detailsOfElements")
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected details response cardinality.")
    boxes = await _boxes(client, port, guids)
    items = []
    for index, (move, row) in enumerate(zip(moves, rows, strict=True)):
        if not isinstance(row, dict) or "error" in row:
            raise ValueError(f"Element {move.guid}: cannot read it ({row}).")
        if row.get("hotlinkId"):
            raise ValueError(f"Element {move.guid} belongs to a hotlink and is read-only.")
        if not boxes[move.guid]:
            raise ValueError(f"Element {move.guid}: no bounding box, so a move cannot be checked.")
        items.append(
            {
                "index": index,
                "status": "ready",
                "element_guid": move.guid,
                "type": row.get("type"),
                "floorIndex": row.get("floorIndex"),
                "layerIndex": row.get("layerIndex"),
                "before": boxes[move.guid],
                "parameters": {
                    "elementId": {"guid": move.guid},
                    "moveVector": move.vector.model_dump(),
                    "copy": False,
                },
            }
        )
    return {"operation": operation, "target": target, "items": items}


def _move_mismatches(item: dict, after: dict) -> list[str]:
    v = item["parameters"]["moveVector"]
    shift = {"x": v["x"], "y": v["y"], "z": v["z"]}
    differences = []
    for mode, before in item["before"].items():
        now = after.get(mode)
        if now is None:
            differences.append(f"{mode}: box missing after the move")
            continue
        for key, value in before.items():
            expected = value + shift[key[0]]
            if not math.isclose(
                now.get(key, math.nan), expected, rel_tol=0.0, abs_tol=MOVE_TOLERANCE
            ):
                differences.append(f"{mode}.{key}")
    return differences


async def _move_dispatch(client: ArchicadClient, receipt: dict) -> None:
    items, port = receipt["items"], receipt["target"]["port"]
    try:
        raw = await client.tapir(
            port,
            "MoveElements",
            {"elementsWithMoveVectors": [i["parameters"] for i in items]},
            timeout=receipt["write_timeout_seconds"],
        )
    except ArchicadError as exc:
        for item in items:
            item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Move outcome is unknown. Inspect Archicad; do not retry this plan."
        return
    receipt["raw_response"] = raw
    rows = raw.get("executionResults")
    if not isinstance(rows, list) or len(rows) != len(items):
        for item in items:
            item.update(
                status="unknown", error="Unexpected response cardinality; inspect Archicad."
            )
        return
    moved = []
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        if isinstance(row, dict) and row.get("success") is True:
            item["status"] = "unverified"
            moved.append(item)
        elif isinstance(row, dict) and row.get("success") is False:
            item.update(status="failed", error=row.get("error"))
        else:
            item.update(status="unknown", error="Unexpected move result; inspect Archicad.")
    if not moved:
        return
    try:
        after = await _boxes(client, port, [i["element_guid"] for i in moved])
        for item in moved:
            item["after"] = after[item["element_guid"]]
            differences = _move_mismatches(item, item["after"])
            item.update(status="verification_failed" if differences else "verified")
            if differences:
                item["mismatches"] = differences
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)


async def move_elements(
    client: ArchicadClient,
    moves: list[dict | ElementMove],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply moving up to 50 elements, each by its own vector in metres.

    Never copies. Refuses hotlinked, unknown or box-less elements in the preview, and
    checks every 2D/3D box moved by its vector (1 mm) after applying. Never saves.
    """
    if not 1 <= len(moves) <= MAX_MOVES:
        raise ValueError(f"Pass between 1 and {MAX_MOVES} moves.")
    validated = [m if isinstance(m, ElementMove) else ElementMove.model_validate(m) for m in moves]
    guids = [m.guid for m in validated]
    if len(set(guids)) != len(guids):
        raise ValueError("Each element may appear only once per call.")
    return await _write(client, validated, port, dry_run, confirmation_token, "move_elements")


# Scalar property value types this tool writes; lists and enumerations are refused.
SCALAR_TYPES = {
    "string": str,
    "boolean": bool,
    "integer": int,
    "number": float,
    "length": float,
    "area": float,
    "volume": float,
    "angle": float,
}


class PropertyChange(InputModel):
    element_guid: str
    property_guid: str
    value: str | bool | int | float

    @field_validator("element_guid", "property_guid")
    @classmethod
    def canonical_guid(cls, value: str) -> str:
        return str(UUID(value)).upper()


def _coerce(kind: str, value: Any) -> Any:
    expected = SCALAR_TYPES[kind]
    if expected is bool:
        if not isinstance(value, bool):
            raise ValueError("needs true or false")
        return value
    if expected is str:
        if not isinstance(value, str):
            raise ValueError("needs text")
        return value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("needs a number")
    if expected is int:
        if float(value) != int(value):
            raise ValueError("needs a whole number")
        return int(value)
    if not math.isfinite(value):
        raise ValueError("needs a finite number")
    return float(value)


async def _read_values(
    client: ArchicadClient, port: int, pairs: list[tuple[str, str]], timeout: float | None = None
) -> dict[tuple[str, str], Any]:
    """Current value (or error) of each (element, property) pair, one request per element."""
    out: dict[tuple[str, str], Any] = {}
    by_element: dict[str, list[str]] = {}
    for element, prop in pairs:
        by_element.setdefault(element, []).append(prop)
    elements = list(by_element)
    properties = sorted({prop for _, prop in pairs})
    extra = {} if timeout is None else {"timeout": timeout}
    result = await client.command(
        port,
        "GetPropertyValuesOfElements",
        {
            "elements": element_ids(elements),
            "properties": [{"propertyId": {"guid": g}} for g in properties],
        },
        **extra,
    )
    rows = result.get("propertyValuesForElements")
    if not isinstance(rows, list) or len(rows) != len(elements):
        raise ValueError("Unexpected property value response cardinality.")
    for element, row in zip(elements, rows, strict=True):
        values = row.get("propertyValues") if isinstance(row, dict) else None
        for index, prop in enumerate(properties):
            if (element, prop) not in pairs:
                continue
            if not isinstance(values, list) or len(values) != len(properties):
                out[(element, prop)] = {"error": row.get("error") if isinstance(row, dict) else row}
            else:
                out[(element, prop)] = values[index]
    return out


async def _property_plan(
    client: ArchicadClient, changes: list[PropertyChange], port: int | None, operation: str
) -> dict:
    port, target, _ = await _context(client, port)
    pairs = [(c.element_guid, c.property_guid) for c in changes]
    current = await _read_values(client, port, pairs)
    definitions = await client.command(
        port,
        "GetDetailsOfProperties",
        {"properties": [{"propertyId": {"guid": g}} for g in sorted({p for _, p in pairs})]},
    )
    names = {}
    for row in definitions.get("propertyDefinitions", []):
        definition = row.get("propertyDefinition") if isinstance(row, dict) else None
        # Live shape (AC30 build 3001): the GUID is under propertyId, not a "guid" key.
        identifier = definition.get("propertyId") if isinstance(definition, dict) else None
        if isinstance(identifier, dict) and identifier.get("guid"):
            names[str(identifier["guid"]).upper()] = definition
    items = []
    for index, change in enumerate(changes):
        label = f"Change {index} ({change.element_guid} / {change.property_guid})"
        definition = names.get(change.property_guid, {})
        if definition.get("isEditable") is False:
            raise ValueError(f"{label}: the property is read-only.")
        row = current[(change.element_guid, change.property_guid)]
        value = row.get("propertyValue") if isinstance(row, dict) else None
        if not isinstance(value, dict):
            raise ValueError(f"{label}: cannot read the current value ({row}).")
        kind = value.get("type")
        if kind not in SCALAR_TYPES:
            raise ValueError(f"{label}: value type {kind!r} is not supported yet.")
        if value.get("status") == "notAvailable":
            raise ValueError(f"{label}: the property is not available for this element.")
        try:
            new = _coerce(kind, change.value)
        except ValueError as exc:
            raise ValueError(f"{label}: a {kind} property {exc}.") from None
        items.append(
            {
                "index": index,
                "status": "ready",
                "element_guid": change.element_guid,
                "property_guid": change.property_guid,
                "property_name": definition.get("name"),
                "before": value,
                "parameters": {
                    "elementId": {"guid": change.element_guid},
                    "propertyId": {"guid": change.property_guid},
                    "propertyValue": {"type": kind, "status": "normal", "value": new},
                },
            }
        )
    return {"operation": operation, "target": target, "items": items}


def _same_value(expected: dict, actual: Any) -> bool:
    if not isinstance(actual, dict) or actual.get("type") != expected["type"]:
        return False
    a, b = expected["value"], actual.get("value")
    if isinstance(a, float) and isinstance(b, (int, float)) and not isinstance(b, bool):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)
    return a == b and type(a) is type(b)


async def _property_dispatch(client: ArchicadClient, receipt: dict) -> None:
    items, port = receipt["items"], receipt["target"]["port"]
    try:
        raw = await client.command(
            port,
            "SetPropertyValuesOfElements",
            {"elementPropertyValues": [i["parameters"] for i in items]},
            timeout=receipt["write_timeout_seconds"],
        )
    except ArchicadError as exc:
        for item in items:
            item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Outcome is unknown. Inspect Archicad; do not retry this plan."
        return
    receipt["raw_response"] = raw
    rows = raw.get("executionResults")
    if not isinstance(rows, list) or len(rows) != len(items):
        for item in items:
            item.update(
                status="unknown", error="Unexpected response cardinality; inspect Archicad."
            )
        return
    written = []
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        if isinstance(row, dict) and row.get("success") is True:
            item["status"] = "unverified"
            written.append(item)
        elif isinstance(row, dict) and row.get("success") is False:
            item.update(status="failed", error=row.get("error"))
        else:
            item.update(status="unknown", error="Unexpected result; inspect Archicad.")
    if not written:
        return
    try:
        after = await _read_values(
            client,
            port,
            [(i["element_guid"], i["property_guid"]) for i in written],
            receipt["write_timeout_seconds"],
        )
        for item in written:
            row = after[(item["element_guid"], item["property_guid"])]
            item["after"] = row.get("propertyValue") if isinstance(row, dict) else row
            ok = _same_value(item["parameters"]["propertyValue"], item["after"])
            item["status"] = "verified" if ok else "verification_failed"
            if not ok:
                item["mismatches"] = ["propertyValue"]
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)


async def set_property_values(
    client: ArchicadClient,
    changes: list[dict | PropertyChange],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 100 property values (element + property + new value).

    Scalar types only (text, number, integer, boolean, length, area, volume, angle).
    The preview shows the current and new value and refuses read-only or unavailable
    properties; applying reads every value back. Never saves.
    """
    if not 1 <= len(changes) <= MAX_PROPERTY_CHANGES:
        raise ValueError(f"Pass between 1 and {MAX_PROPERTY_CHANGES} property changes.")
    validated = [
        c if isinstance(c, PropertyChange) else PropertyChange.model_validate(c) for c in changes
    ]
    pairs = [(c.element_guid, c.property_guid) for c in validated]
    if len(set(pairs)) != len(pairs):
        raise ValueError("Each element and property pair may appear only once per call.")
    return await _write(client, validated, port, dry_run, confirmation_token, "set_property_values")


async def _delete_plan(
    client: ArchicadClient, guids: list[str], port: int | None, operation: str
) -> dict:
    port, target, _ = await _context(client, port)
    if target["project"].get("isUntitled") is not True:
        raise ValueError("Deletion requires an untitled test project (isUntitled=true).")
    elements = element_ids(guids)
    details = await client.tapir(
        port,
        "GetDetailsOfElements",
        {"elements": elements, "fields": ["type", "floorIndex", "layerIndex", "hotlinkId"]},
    )
    rows = details.get("detailsOfElements")
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected deletion details response cardinality.")
    for guid, row in zip(guids, rows, strict=True):
        if not isinstance(row, dict) or "error" in row or not row.get("type"):
            raise ValueError(f"Element {guid} does not exist or cannot be read.")
        if row.get("hotlinkId"):
            raise ValueError(f"Element {guid} belongs to a hotlink.")
        if not all(
            isinstance(row.get(key), int) and not isinstance(row[key], bool)
            for key in ("floorIndex", "layerIndex")
        ):
            raise ValueError(f"Element {guid}: missing story/layer data.")
    editable = await client.tapir(
        port, "FilterElements", {"elements": elements, "filters": ["IsEditable"]}
    )
    editable_rows = editable.get("elements")
    if not isinstance(editable_rows, list):
        raise ValueError("Unexpected editable-filter response.")
    editable_guids = {e["elementId"]["guid"].upper() for e in editable_rows}
    if set(guids) - editable_guids:
        raise ValueError("Locked/non-editable elements cannot be deleted.")
    return {
        "operation": operation,
        "target": target,
        "items": [
            {
                "index": index,
                "status": "ready",
                "element_guid": guid,
                "before": row,
                "parameters": {"elementId": {"guid": guid}},
            }
            for index, (guid, row) in enumerate(zip(guids, rows, strict=True))
        ],
    }


async def _delete_dispatch(client: ArchicadClient, receipt: dict) -> None:
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    # Recheck immediately before the destructive command, including after journaling.
    try:
        project = await client.tapir(port, "GetProjectInfo", timeout=timeout)
        if project != receipt["target"]["project"] or project.get("isUntitled") is not True:
            for item in items:
                item.update(status="failed", error="Project changed; deletion not dispatched.")
            return
        raw = await client.tapir(
            port, "DeleteElements", {"elements": [i["parameters"] for i in items]}, timeout=timeout
        )
    except ArchicadError as exc:
        for item in items:
            item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Outcome unknown; inspect Archicad and never retry this token."
        return
    receipt["raw_response"] = raw
    rows = raw.get("executionResults")
    if not isinstance(rows, list) or len(rows) != len(items):
        for item in items:
            item.update(status="unknown", error="Unexpected deletion response cardinality.")
        return
    deleted = []
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        if isinstance(row, dict) and row.get("success") is True:
            item["status"] = "unverified"
            deleted.append(item)
        elif isinstance(row, dict) and row.get("success") is False and "error" in row:
            item.update(status="failed", error=row["error"])
        else:
            item.update(status="unknown", error="Unexpected deletion result.")
    if not deleted:
        return
    try:
        response = await client.command(port, "GetAllElements", timeout=timeout)
        remaining = response.get("elements")
        if not isinstance(remaining, list):
            raise ValueError("Unexpected deletion verification response.")
        present = {e["elementId"]["guid"].upper() for e in remaining}
        for item in deleted:
            exists = item["element_guid"] in present
            item["after"] = {"exists": exists}
            item["status"] = "verification_failed" if exists else "verified"
            if exists:
                item["mismatches"] = ["element still exists"]
    except (ArchicadError, ValueError, KeyError, TypeError) as exc:
        receipt["verification_error"] = str(exc)


async def delete_elements(
    client: ArchicadClient,
    element_guids: list[str],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Delete up to 50 editable, non-hotlinked elements in an untitled test project.

    Uses Tapir DeleteElements (not an official JSON API command). Preview lists type,
    story and layer. Single-use token, explicit port, receipts, absence verification.
    No saves, unlocking, or automatic retries. Archicad may remove owned subelements.
    """
    if not 1 <= len(element_guids) <= 50:
        raise ValueError("Pass between 1 and 50 element GUIDs.")
    guids = [item["elementId"]["guid"] for item in element_ids(element_guids)]
    if len(set(guids)) != len(guids):
        raise ValueError("Duplicate element GUIDs are not allowed.")
    return await _write(client, guids, port, dry_run, confirmation_token, "delete_elements")


NAMED_PREVIEWS = {
    "move_elements",
    "set_property_values",
    "set_classifications",
    "set_element_layers",
    "apply_favorites",
    "create_lines",
    "create_polylines",
    "create_splines",
    "create_arcs",
    "create_circles",
    "create_fills",
    "delete_elements",
    "rotate_elements",
    "set_gdl_parameters",
    "modify_walls",
    "modify_slabs",
    "modify_columns",
    "modify_beams",
    "modify_windows",
    "modify_doors",
    "modify_objects",
    "modify_roofs",
    "modify_texts",
    "create_windows",
    "create_doors",
    "lock_elements",
    "unlock_elements",
}


def _plan_digest(plan: dict) -> str:
    """Display names are not model identity; indices and story levels still are."""
    comparable = deepcopy(plan)
    if plan["operation"] in NAMED_PREVIEWS:
        for story in comparable["target"]["stories"]:
            story.pop("name", None)
        for item in comparable["items"]:
            item.pop("floorName", None)
            item.pop("layerName", None)
    return _digest(comparable)


async def _preview_names(client: ArchicadClient, plan: dict) -> None:
    if plan["operation"] not in NAMED_PREVIEWS:
        return
    port = plan["target"]["port"]
    items = plan["items"]
    # Property previews did not need element geometry; read just the two indices once.
    if plan["operation"] == "set_property_values":
        guids = list(dict.fromkeys(i["element_guid"] for i in items))
        response = await client.tapir(
            port,
            "GetDetailsOfElements",
            {"elements": element_ids(guids), "fields": ["floorIndex", "layerIndex"]},
        )
        rows = response.get("detailsOfElements", [])
        indices = dict(zip(guids, rows, strict=False)) if isinstance(rows, list) else {}
        for item in items:
            row = indices.get(item["element_guid"], {})
            for key in ("floorIndex", "layerIndex"):
                item[key] = row.get(key) if isinstance(row, dict) else None
    floors = {story["index"]: story.get("name") for story in plan["target"]["stories"]}
    layers = {}
    try:
        response = await client.tapir(port, "GetAttributesByType", {"attributeType": "Layer"})
        for row in response.get("attributes", []):
            if isinstance(row, dict) and isinstance(row.get("name"), str):
                layers[row.get("index")] = row["name"]
    except ArchicadError:
        pass  # A display-name lookup must not prevent a safe preview.
    for item in items:
        before = item.get("before", {})
        for key in ("floorIndex", "layerIndex"):
            if key not in item:
                item[key] = before.get(key) if isinstance(before, dict) else None
        item["floorName"] = floors.get(item["floorIndex"])
        item["layerName"] = layers.get(item["layerIndex"])


def _beam_payload(beam: BeamCreate) -> dict:
    return {
        "begCoordinate": beam.start.model_dump(),
        "endCoordinate": beam.end.model_dump(),
        "floorIndex": beam.floor_index,
        "zCoordinate": beam.level,
        "width": beam.width,
        "height": beam.height,
        "offset": 0.0,
        "slantAngle": 0.0,
        "isSlanted": False,
        "profileAngle": 0.0,
        "arcAngle": 0.0,
        "verticalCurveHeight": 0.0,
        "anchorPoint": "Center",
        "circleBased": False,
        "isWidthAndHeightLinked": False,
    }


def _beam_mismatches(item: dict, row: Any, target: dict) -> list[str]:
    p = item["parameters"]
    story = next(s for s in target["stories"] if s["index"] == p["floorIndex"])
    details = {key: value for key, value in p.items() if key != "floorIndex"}
    details.update(level=p["zCoordinate"] - story["level"], beamShape="Straight")
    differences = _mismatches(
        {"type": "Beam", "floorIndex": p["floorIndex"], "details": details}, row
    )
    if (
        isinstance(row, dict)
        and isinstance(row.get("details"), dict)
        and "profileId" in row["details"]
    ):
        differences.append("details.profileId")
    return differences


async def create_beams(
    client: ArchicadClient,
    beams: list[dict | BeamCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 straight rectangular beams; all lengths in metres.

    level is absolute project Z. Centered, unrotated, unlinked rectangular section.
    Requires Tapir; shares single-use token, explicit port, per-beam receipts and timeout.
    Verifies geometry/section after writing. Inherited profiles may fail verification.
    Never saves. Tapir details describe the first segment of a multi-segment default.
    """
    if not 1 <= len(beams) <= 20:
        raise ValueError("Pass between 1 and 20 beams.")
    validated = [b if isinstance(b, BeamCreate) else BeamCreate.model_validate(b) for b in beams]
    return await _write(client, validated, port, dry_run, confirmation_token, "create_beams")


def _zone_payload(zone: ZoneCreate) -> dict:
    return {
        "floorIndex": zone.floor_index,
        "name": zone.name,
        "numberStr": zone.number,
        "geometry": {
            "polygonCoordinates": [p.model_dump() for p in zone.outline],
            "polygonArcs": [],
            "holes": [],
        },
    }


def _zone_mismatches(item: dict, row: Any) -> list[str]:
    p = item["parameters"]
    differences = _mismatches(
        {
            "type": "Zone",
            "floorIndex": p["floorIndex"],
            "details": {
                "name": p["name"],
                "numberStr": p["numberStr"],
                "isManual": True,
                "holes": [],
            },
        },
        row,
    )
    details = row.get("details", {}) if isinstance(row, dict) else {}
    # Tapir 1.7.0 omits polygonArcs when the outline has no arcs (as for slabs).
    if isinstance(details, dict) and details.get("polygonArcs", []) != []:
        differences.append("details.polygonArcs")
    outline = details.get("polygonOutline") if isinstance(details, dict) else None
    wanted = p["geometry"]["polygonCoordinates"]
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
    return differences


async def create_zones(
    client: ArchicadClient,
    zones: list[dict | ZoneCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 manually bounded zones. Outline coordinates in metres.

    Simple straight polygon, no arcs/holes; same validation as slabs. Name, number,
    story and contour verified after creation. Category/stamp/base defaults inherited.
    Shared single-use confirmation/explicit port/receipts/timeout; never saves.
    """
    if not 1 <= len(zones) <= 20:
        raise ValueError("Pass between 1 and 20 zones.")
    validated = [z if isinstance(z, ZoneCreate) else ZoneCreate.model_validate(z) for z in zones]
    return await _write(client, validated, port, dry_run, confirmation_token, "create_zones")


OPERATIONS["add_comment_to_issue"] = (
    "issue comment", "comment_receipt_id", "Adds comments only; each comment is one Undo step."
)

OPERATIONS.update({
    "create_view_map_folders": (
        "View Map folder", "folder_receipt_id",
        "No guaranteed Navigator Undo; remove new folders manually."
    ),
    "clone_to_view_map": (
        "View Map clone", "view_receipt_id",
        "No guaranteed Navigator Undo; native settings are inherited."
    ),
})

OPERATIONS["create_classification_items"] = (
    "classification item", "classification_item_receipt_id",
    "Creates only under existing parents; each item is one native Undo step."
)
