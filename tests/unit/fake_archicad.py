"""A fake Archicad that answers like the JSON API, for tests without Archicad.

Each FakeArchicad stands for one running instance on one port. `fake_transport`
routes requests by port; ports with no instance refuse the connection, like a
real machine.
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx

CREATE_WALLS_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "ac30_tapir170_create_walls.json").read_text(
        encoding="utf-8"
    )
)


# Official documentation/source-derived format; not a live capture.
BUILDING_MATERIALS_FIXTURE = json.loads(
    (
        Path(__file__).parents[1] / "fixtures" / "tapir170_building_materials_documented.json"
    ).read_text(encoding="utf-8")
)

# Documentation/source-derived; explicitly not a live response capture.
CREATE_SLABS_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "tapir170_create_slabs_documented.json").read_text(
        encoding="utf-8"
    )
)


# Documentation-derived JSON API format, not a live capture.
BOUNDING_BOXES_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "json_api_bounding_boxes_documented.json").read_text(
        encoding="utf-8"
    )
)


# Live GetDetailsOfElements capture: AC30 build 3001 BRA, Windows, Tapir 1.7.0.
CREATE_COLUMNS_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "tapir170_create_columns_documented.json").read_text(
        encoding="utf-8"
    )
)


# Window/Door details captured live (AC30 build 3001 BRA, Tapir 1.7.0); see the fixture.
CREATE_OPENINGS_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "tapir170_create_openings_documented.json").read_text(
        encoding="utf-8"
    )
)


# Tapir 1.7.0 source-derived Modify* results; explicitly not a live capture.
MODIFY_ELEMENTS_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "tapir170_modify_elements_documented.json").read_text(
        encoding="utf-8"
    )
)
# command -> (element type it edits, list key)
MODIFY_COMMANDS = {
    "ModifySlabs": ("Slab", "slabsWithDetails"),
    "ModifyColumns": ("Column", "columnsWithDetails"),
    "ModifyBeams": ("Beam", "beamsWithDetails"),
    "ModifyWindows": ("Window", "windowsWithDetails"),
    "ModifyDoors": ("Door", "doorsWithDetails"),
    "ModifyObjects": ("Object", "objectsWithDetails"),
}


def ok(result: Any) -> dict:
    return {"succeeded": True, "result": result}


def fail(code: int, message: str) -> dict:
    return {"succeeded": False, "error": {"code": code, "message": message}}


@dataclass
class FakeArchicad:
    port: int
    version: int = 29
    build: int = 3000
    language: str = "BRA"
    project_name: str = "Projeto teste"
    tapir_version: str | None = "1.7.0"
    busy: bool = False
    elements: dict[str, str] = field(default_factory=dict)  # guid -> type
    selection: list[str] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)  # guid -> name
    stories: list[dict] = field(
        default_factory=lambda: [{"index": 0, "name": "Térreo", "level": 0.0}]
    )
    details: dict[str, dict] = field(default_factory=dict)
    create_errors: dict[int, dict] = field(default_factory=dict)
    lose_create_response: bool = False
    building_materials: dict[str, dict] = field(default_factory=dict)
    layers: dict[int, str | None] = field(default_factory=lambda: {1: "Walls"})
    lose_slab_response: bool = False
    lose_zone_response: bool = False
    lose_beam_response: bool = False
    lose_column_response: bool = False
    lose_object_response: bool = False
    lose_opening_response: bool = False
    favorites: dict[str, list[str]] = field(
        default_factory=lambda: deepcopy({"Window": ["Janela padrão"], "Door": ["Porta padrão"]})
    )
    # Library part names CreateObjects can find; any other name fails that item.
    library_inventory: list[dict] | None = None
    library_skipped_count: int = 0
    library_parts: set[str] = field(default_factory=lambda: {"Mesa Retangular 30"})
    lose_delete_response: bool = False
    delete_ignored: bool = False
    delete_errors: dict[int, dict] = field(default_factory=dict)
    locked_elements: set[str] = field(default_factory=set)
    modify_wall_errors: dict[int, dict] = field(default_factory=dict)
    modify_wall_ignored: bool = False
    lose_modify_wall_response: bool = False
    # ModifySlabs/Columns/Beams/Windows/Doors/Objects
    modify_errors: dict[int, dict] = field(default_factory=dict)
    modify_ignored: bool = False
    lose_modify_response: bool = False
    gdl_parameters: dict[str, list] = field(default_factory=dict)
    gdl_errors: dict[int, dict] = field(default_factory=dict)
    gdl_ignored: bool = False
    lose_gdl_response: bool = False
    lose_rotate_response: bool = False
    rotate_errors: dict[int, dict] = field(default_factory=dict)
    rotate_ignored: bool = False
    lose_move_response: bool = False
    move_errors: dict[int, dict] = field(default_factory=dict)
    move_ignored: bool = False  # report success without moving (verification test)
    # (element guid, property guid) -> {"type", "status", "value"}; default is a text "x".
    property_values: dict[tuple[str, str], dict] = field(default_factory=dict)
    read_only_properties: set[str] = field(default_factory=set)
    property_set_errors: dict[int, dict] = field(default_factory=dict)
    property_set_ignored: bool = False
    cut_fills: dict[str, list] = field(default_factory=dict)  # guid -> polygons
    bounding_boxes_2d: dict[str, dict] = field(default_factory=dict)
    bounding_boxes_3d: dict[str, dict] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    command_requests: list[dict] = field(default_factory=list)
    tapir_calls: list[str] = field(default_factory=list)
    tapir_requests: list[dict] = field(default_factory=list)

    def handle(self, body: dict) -> dict:
        command = body.get("command", "")
        params = body.get("parameters", {})
        self.calls.append(command)
        self.command_requests.append(deepcopy(body))
        if self.busy:
            return fail(4001, "Invalid program status (ongoing user input)")
        if command == "API.GetProductInfo":
            return ok(
                {"version": self.version, "buildNumber": self.build, "languageCode": self.language}
            )
        if command in {"API.Get2DBoundingBoxes", "API.Get3DBoundingBoxes"}:
            dimension = "2D" if command == "API.Get2DBoundingBoxes" else "3D"
            configured = self.bounding_boxes_2d if dimension == "2D" else self.bounding_boxes_3d
            default = BOUNDING_BOXES_FIXTURE[dimension.lower()][f"boundingBoxes{dimension}"][0]
            out = []
            for element in params["elements"]:
                guid = element["elementId"]["guid"]
                row = configured.get(
                    guid, default if guid in self.elements else BOUNDING_BOXES_FIXTURE["error"]
                )
                out.append(deepcopy(row))
            return ok({f"boundingBoxes{dimension}": out})
        if command == "API.GetAllElements":
            return ok({"elements": [self._id(g) for g in self.elements]})
        if command == "API.GetElementsByType":
            kind = params["elementType"]
            return ok({"elements": [self._id(g) for g, t in self.elements.items() if t == kind]})
        if command == "API.GetSelectedElements":
            return ok({"elements": [self._id(g) for g in self.selection]})
        if command == "API.GetAllPropertyIds":
            return ok({"propertyIds": [{"propertyId": {"guid": g}} for g in self.properties]})
        if command == "API.GetDetailsOfProperties":
            out = []
            for p in params["properties"]:
                g = p["propertyId"]["guid"]
                # Key layout seen live on AC30 build 3001 (propertyId.guid, not "guid").
                definition = {"propertyId": {"guid": g}, "name": self.properties[g]}
                if g in self.read_only_properties:
                    definition["isEditable"] = False
                out.append({"propertyDefinition": definition})
            return ok({"propertyDefinitions": out})
        if command == "API.GetPropertyValuesOfElements":
            rows = []
            for e in params["elements"]:
                g = e["elementId"]["guid"]
                if g not in self.elements:
                    rows.append({"error": {"code": 4002, "message": "Element not found"}})
                else:
                    rows.append(
                        {
                            "propertyValues": [
                                {
                                    "propertyValue": deepcopy(
                                        self.property_values.get(
                                            (g, p["propertyId"]["guid"]),
                                            {"type": "string", "status": "normal", "value": "x"},
                                        )
                                    )
                                }
                                for p in params["properties"]
                            ]
                        }
                    )
            return ok({"propertyValuesForElements": rows})
        if command == "API.SetPropertyValuesOfElements":
            # Shape from the official JSON API documentation; not a live capture.
            results = []
            for index, entry in enumerate(params["elementPropertyValues"]):
                g, p = entry["elementId"]["guid"], entry["propertyId"]["guid"]
                if index in self.property_set_errors:
                    results.append(deepcopy(self.property_set_errors[index]))
                elif g not in self.elements:
                    error = {"code": 4002, "message": "Element not found"}
                    results.append({"success": False, "error": error})
                else:
                    if not self.property_set_ignored:
                        self.property_values[(g, p)] = deepcopy(entry["propertyValue"])
                    results.append({"success": True})
            return ok({"executionResults": results})
        if command == "API.ExecuteAddOnCommand":
            return self._tapir(params)
        return fail(4000, f"Unknown command {command}")

    def _tapir(self, params: dict) -> dict:
        if self.tapir_version is None:
            return fail(4010, "Add-On command is not registered")
        name = params["addOnCommandId"]["commandName"]
        args = params.get("addOnCommandParameters", {})
        self.tapir_calls.append(name)
        self.tapir_requests.append({"command": name, "parameters": deepcopy(args)})
        if name == "GetAddOnVersion":
            return ok({"addOnCommandResponse": {"version": self.tapir_version}})
        if name == "GetProjectInfo":
            return ok(
                {
                    "addOnCommandResponse": {
                        "isUntitled": not self.project_name,
                        "isTeamwork": False,
                        "projectName": self.project_name,
                    }
                }
            )
        if name == "GetAttributesByType" and args["attributeType"] == "Layer":
            # Official Tapir schema in tapir170_layers_documented.json; not live captured.
            fixture = json.loads(
                (
                    Path(__file__).parents[1] / "fixtures" / "tapir170_layers_documented.json"
                ).read_text(encoding="utf-8")
            )
            rows = [
                {**deepcopy(fixture["attributes"][0]), "index": index, "name": name}
                for index, name in self.layers.items()
            ]
            return ok({"addOnCommandResponse": {"attributes": rows}})
        if name == "GetAttributesByType":
            assert args["attributeType"] == "BuildingMaterial"
            return ok(
                {
                    "addOnCommandResponse": {
                        "attributes": [
                            {key: deepcopy(row[key]) for key in ("attributeId", "index", "name")}
                            for row in self.building_materials.values()
                            if "error" not in row
                        ]
                    }
                }
            )
        if name == "GetBuildingMaterials":
            out = []
            for attribute in args["attributeIds"]:
                guid = attribute["attributeId"]["guid"]
                row = self.building_materials.get(guid, BUILDING_MATERIALS_FIXTURE["error"])
                if "error" in row:
                    out.append(deepcopy(row))
                else:
                    keys = {"attributeId", "index", "name", *args["fields"]}
                    out.append({key: deepcopy(value) for key, value in row.items() if key in keys})
            return ok({"addOnCommandResponse": {"buildingMaterials": out}})
        if name == "GetStories":
            return ok({"addOnCommandResponse": {"stories": self.stories}})
        if name == "GetDetailsOfElements":
            out = []
            for e in args["elements"]:
                g = e["elementId"]["guid"]
                full = self.details.get(g, {"type": self.elements.get(g, "Unknown")})
                row = {key: deepcopy(value) for key, value in full.items() if key in args["fields"]}
                # Like Tapir 1.7.0: the key is only present when a cut fill was found.
                if "floorPlanPolygons" in args["fields"] and g in self.cut_fills:
                    row["floorPlanPolygons"] = self.cut_fills[g]
                out.append(row)
            return ok({"addOnCommandResponse": {"detailsOfElements": out}})
        if name == "FilterElements":
            # Tapir source-derived schema; not a live capture. No unlocking.
            assert args["filters"] == ["IsEditable"]
            return ok(
                {
                    "addOnCommandResponse": {
                        "elements": [
                            deepcopy(e)
                            for e in args["elements"]
                            if e["elementId"]["guid"] in self.elements
                            and e["elementId"]["guid"] not in self.locked_elements
                        ]
                    }
                }
            )
        if name == "DeleteElements":
            fixture = json.loads(
                (
                    Path(__file__).parents[1]
                    / "fixtures"
                    / "tapir170_delete_elements_documented.json"
                ).read_text(encoding="utf-8")
            )
            rows = []
            for index, element in enumerate(args["elements"]):
                guid = element["elementId"]["guid"]
                if index in self.delete_errors:
                    rows.append(deepcopy(self.delete_errors[index]))
                elif guid in self.locked_elements:
                    rows.append(deepcopy(fixture["failure"]))
                else:
                    if not self.delete_ignored:
                        self.elements.pop(guid, None)
                        self.details.pop(guid, None)
                    rows.append(deepcopy(fixture["success"]))
            return ok({"addOnCommandResponse": {"executionResults": rows}})
        if name == "ModifyWalls":
            # Official Tapir source at 02691b5d; synthetic fixture, not live captured.
            fixture = json.loads(
                (
                    Path(__file__).parents[1] / "fixtures" / "tapir170_modify_walls_documented.json"
                ).read_text(encoding="utf-8")
            )
            rows = []
            for index, entry in enumerate(args["wallsWithDetails"]):
                guid = entry["elementId"]["guid"]
                if index in self.modify_wall_errors:
                    rows.append(deepcopy(self.modify_wall_errors[index]))
                    continue
                if self.elements.get(guid) != "Wall" or guid in self.locked_elements:
                    rows.append(deepcopy(fixture["failure"]))
                    continue
                if not self.modify_wall_ignored:
                    details = self.details[guid]["details"]
                    for key in ("height", "bottomOffset", "begCoordinate", "endCoordinate"):
                        if key in entry:
                            details[key] = deepcopy(entry[key])
                    if "height" in entry:
                        details["relativeTopStory"] = 0
                    if "thickness" in entry:
                        details["begThickness"] = entry["thickness"]
                    if "bottomOffset" in entry:
                        story = next(
                            s
                            for s in self.stories
                            if s["index"] == self.details[guid]["floorIndex"]
                        )
                        details["zCoordinate"] = story["level"] + entry["bottomOffset"]
                rows.append(deepcopy(fixture["success"]))
            return ok({"addOnCommandResponse": {"executionResults": rows}})
        if name in MODIFY_COMMANDS:
            return self._modify(name, args)
        if name in {"GetGDLParametersOfElements", "SetGDLParametersOfElements"}:
            # Official Tapir schema at 02691b5d; synthetic fixture, not live captured.
            fixture = json.loads(
                (
                    Path(__file__).parents[1]
                    / "fixtures"
                    / "tapir170_gdl_parameters_documented.json"
                ).read_text(encoding="utf-8")
            )
            if name == "GetGDLParametersOfElements":
                rows = []
                for element in args["elements"]:
                    guid = element["elementId"]["guid"]
                    if self.elements.get(guid) != "Object":
                        rows.append({"error": {"code": -1, "message": "Not an Object"}})
                    else:
                        parameters = self.gdl_parameters.setdefault(
                            guid, deepcopy(fixture["parameters"])
                        )
                        rows.append({"parameters": deepcopy(parameters)})
                return ok({"addOnCommandResponse": {"gdlParametersOfElements": rows}})
            rows = []
            for index, entry in enumerate(args["elementsWithGDLParameters"]):
                guid = entry["elementId"]["guid"]
                if index in self.gdl_errors:
                    rows.append(deepcopy(self.gdl_errors[index]))
                    continue
                parameters = self.gdl_parameters.get(guid, [])
                wanted = entry["gdlParameters"][0]
                matches = [p for p in parameters if p["name"] == wanted["name"]]
                if len(matches) != 1 or guid in self.locked_elements:
                    rows.append(deepcopy(fixture["failure"]))
                else:
                    if not self.gdl_ignored:
                        matches[0]["value"] = deepcopy(wanted["value"])
                    rows.append({"success": True})
            return ok({"addOnCommandResponse": {"executionResults": rows}})
        if name == "RotateElements":
            # Schema source-confirmed at 02691b5d; not a live capture.
            fixture = json.loads(
                (
                    Path(__file__).parents[1]
                    / "fixtures"
                    / "tapir170_rotate_elements_documented.json"
                ).read_text(encoding="utf-8")
            )
            rows = []
            for index, entry in enumerate(args["elementsWithRotations"]):
                guid, rotation = entry["elementId"]["guid"], entry["rotation"]
                if index in self.rotate_errors:
                    rows.append(deepcopy(self.rotate_errors[index]))
                    continue
                if guid not in self.elements or guid in self.locked_elements:
                    rows.append(deepcopy(fixture["failure"]))
                    continue
                assert entry["copy"] is False
                origin, begin, end = (
                    rotation["origin"],
                    rotation["beginPoint"],
                    rotation["endPoint"],
                )
                angle = math.atan2(end["y"] - origin["y"], end["x"] - origin["x"]) - math.atan2(
                    begin["y"] - origin["y"], begin["x"] - origin["x"]
                )

                def rotated(p, origin=origin, angle=angle):
                    x, y = p["x"] - origin["x"], p["y"] - origin["y"]
                    return {
                        **p,
                        "x": origin["x"] + math.cos(angle) * x - math.sin(angle) * y,
                        "y": origin["y"] + math.sin(angle) * x + math.cos(angle) * y,
                    }

                if not self.rotate_ignored:
                    details = self.details.get(guid, {}).get("details", {})
                    for key in ("origin", "begCoordinate", "endCoordinate"):
                        if key in details:
                            details[key] = rotated(details[key])
                    for key in ("angle", "axisRotationAngle"):
                        if key in details:
                            details[key] += angle
                    default = BOUNDING_BOXES_FIXTURE["2d"]["boundingBoxes2D"][0]
                    row = deepcopy(self.bounding_boxes_2d.get(guid, default))
                    box = row["boundingBox2D"]
                    pts = [
                        rotated({"x": x, "y": y})
                        for x in (box["xMin"], box["xMax"])
                        for y in (box["yMin"], box["yMax"])
                    ]
                    row["boundingBox2D"] = {
                        "xMin": min(p["x"] for p in pts),
                        "xMax": max(p["x"] for p in pts),
                        "yMin": min(p["y"] for p in pts),
                        "yMax": max(p["y"] for p in pts),
                    }
                    self.bounding_boxes_2d[guid] = row
                rows.append(deepcopy(fixture["success"]))
            return ok({"addOnCommandResponse": {"executionResults": rows}})
        if name == "MoveElements":
            # Shape from Tapir 1.7.0 source (ElementCommands.cpp); not a live capture.
            out = []
            for index, entry in enumerate(args["elementsWithMoveVectors"]):
                g = entry["elementId"]["guid"]
                if index in self.move_errors:
                    out.append(deepcopy(self.move_errors[index]))
                    continue
                if g not in self.elements:
                    message = f"Failed to move element with guid {g}!"
                    out.append({"success": False, "error": {"code": -1, "message": message}})
                    continue
                if not self.move_ignored:
                    v = entry["moveVector"]
                    for dim, store in (
                        ("2D", self.bounding_boxes_2d),
                        ("3D", self.bounding_boxes_3d),
                    ):
                        default = BOUNDING_BOXES_FIXTURE[dim.lower()][f"boundingBoxes{dim}"][0]
                        row = store.get(g) or deepcopy(default)
                        box = row.get(f"boundingBox{dim}")
                        if box:
                            for key in box:
                                box[key] += v[key[0]]
                        store[g] = row
                out.append({"success": True})
            return ok({"addOnCommandResponse": {"executionResults": out}})
        if name == "CreateZones":
            # Tapir CreateZones source-confirmed at 02691b5d; not a live capture.
            fixture = json.loads(
                (
                    Path(__file__).parents[1] / "fixtures" / "tapir170_create_zones_documented.json"
                ).read_text(encoding="utf-8")
            )
            rows = []
            for index, zone in enumerate(args["zonesData"]):
                if index in self.create_errors:
                    rows.append(deepcopy(self.create_errors[index]))
                    continue
                guid = str(uuid4()).upper()
                self.elements[guid] = "Zone"
                row = deepcopy(fixture["details"])
                row["floorIndex"] = zone["floorIndex"]
                points = deepcopy(zone["geometry"]["polygonCoordinates"])
                row["details"].update(
                    name=zone["name"],
                    numberStr=zone["numberStr"],
                    polygonOutline=points + [deepcopy(points[0])],
                )
                self.details[guid] = row
                rows.append(self._id(guid))
            return ok({"addOnCommandResponse": {"elements": rows}})
        if name == "CreateBeams":
            # Source-confirmed at 02691b5d; synthetic fixture, not live captured.
            fixture = json.loads(
                (
                    Path(__file__).parents[1] / "fixtures" / "tapir170_create_beams_documented.json"
                ).read_text(encoding="utf-8")
            )
            rows = []
            for index, beam in enumerate(args["beamsData"]):
                if index in self.create_errors:
                    rows.append(deepcopy(self.create_errors[index]))
                    continue
                guid = str(uuid4()).upper()
                self.elements[guid] = "Beam"
                row = deepcopy(fixture["details"])
                row["floorIndex"] = beam["floorIndex"]
                story = next(s for s in self.stories if s["index"] == beam["floorIndex"])
                row["details"].update(
                    {k: deepcopy(v) for k, v in beam.items() if k != "floorIndex"}
                )
                row["details"]["level"] = beam["zCoordinate"] - story["level"]
                self.details[guid] = row
                rows.append(self._id(guid))
            return ok({"addOnCommandResponse": {"elements": rows}})
        if name == "CreateColumns":
            out = []
            for index, column in enumerate(args["columnsData"]):
                if index in self.create_errors:
                    out.append(deepcopy(self.create_errors[index]))
                    continue
                guid = str(uuid4()).upper()
                self.elements[guid] = "Column"
                row = deepcopy(
                    CREATE_COLUMNS_FIXTURE[
                        "circular_column_details" if column["circleBased"] else "column_details"
                    ]
                )
                row["floorIndex"] = column["floorIndex"]
                floor = next(s for s in self.stories if s["index"] == column["floorIndex"])
                coords = column["coordinates"]
                row["details"].update(
                    origin={"x": coords["x"], "y": coords["y"]},
                    height=column["height"],
                    zCoordinate=coords["z"],
                    bottomOffset=coords["z"] - floor["level"],
                    width=column["width"],
                    depth=column["depth"],
                    circleBased=column["circleBased"],
                    isWidthAndHeightLinked=(
                        column["circleBased"] or column["isWidthAndHeightLinked"]
                    ),
                    axisRotationAngle=column["axisRotationAngle"],
                    coreAnchor=column["coreAnchor"],
                )
                self.details[guid] = row
                out.append(self._id(guid))
            return ok({"addOnCommandResponse": {"elements": out}})
        if name == "GetAvailableLibraryParts":
            # GetAvailableLibraryParts confirmed in LibraryCommands.cpp/AddOnMain.cpp,
            # Tapir 1.7.0 at 02691b5d; synthetic fixture, not a live capture.
            fixture = json.loads(
                (
                    Path(__file__).parents[1]
                    / "fixtures"
                    / "tapir170_library_parts_documented.json"
                ).read_text(encoding="utf-8")
            )
            rows = (
                deepcopy(self.library_inventory)
                if self.library_inventory is not None
                else [
                    {
                        **deepcopy(fixture["response"]["libraryParts"][0]),
                        "guid": str(UUID(int=index)).upper(),
                        "index": index,
                        "documentName": name,
                        "fileName": f"{name}.gsm",
                    }
                    for index, name in enumerate(sorted(self.library_parts), 1)
                ]
            )
            return ok(
                {
                    "addOnCommandResponse": {
                        "libraryParts": rows,
                        "skippedCount": self.library_skipped_count,
                        "skippedSample": [],
                    }
                }
            )
        if name == "CreateObjects":
            # Shape and not-found error captured live on AC30 build 3001 BRA, Tapir 1.7.0.
            out = []
            for index, obj in enumerate(args["objectsData"]):
                if index in self.create_errors:
                    out.append(deepcopy(self.create_errors[index]))
                    continue
                lookup = {n.casefold(): n for n in self.library_parts}
                found = lookup.get(obj["libraryPartName"].casefold())
                if found is None:
                    message = f"Not found library part with name '{obj['libraryPartName']}'"
                    out.append({"error": {"code": -2130313113, "message": message}})
                    continue
                guid = str(uuid4()).upper()
                self.elements[guid] = "Object"
                self.details[guid] = {
                    "type": "Object",
                    "floorIndex": obj["floorIndex"],
                    "layerIndex": 1,
                    "details": {
                        "libPart": {"name": found},
                        "origin": deepcopy(obj["coordinates"]),
                        "dimensions": {"x": 1.2, "y": 0.8, "z": 0.75},
                        "angle": obj.get("angle", 0.0) % math.tau,
                    },
                }
                out.append(self._id(guid))
            return ok({"addOnCommandResponse": {"elements": out}})
        if name == "GetFavoritesByType":
            return ok(
                {"addOnCommandResponse": {"favorites": self.favorites.get(args["elementType"], [])}}
            )
        if name in ("CreateWindows", "CreateDoors"):
            kind = "Window" if name == "CreateWindows" else "Door"
            key = "windowsData" if kind == "Window" else "doorsData"
            out = []
            for index, data in enumerate(args[key]):
                if index in self.create_errors:
                    out.append(deepcopy(self.create_errors[index]))
                    continue
                wall = data["ownerWallId"]["guid"]
                if self.elements.get(wall) != "Wall":
                    out.append(deepcopy(CREATE_OPENINGS_FIXTURE["missing_wall_error"]))
                    continue
                guid = str(uuid4()).upper()
                self.elements[guid] = kind
                row = deepcopy(CREATE_OPENINGS_FIXTURE[f"{kind.lower()}_details"])
                row["floorIndex"] = self.details.get(wall, {}).get("floorIndex", 0)
                details = row["details"]
                details["ownerElementId"] = {"guid": wall}
                details["centerOffset"] = data["centerOffset"]
                for field_name in ("sillHeight", "width", "height"):
                    if field_name in data:
                        details[field_name] = data[field_name]
                if "favoriteName" in data:
                    details["libPart"]["name"] = f"{data['favoriteName']} (peça)"
                self.details[guid] = row
                out.append(self._id(guid))
            return ok({"addOnCommandResponse": {"elements": out}})
        if name == "CreateSlabs":
            out = []
            for index, slab in enumerate(args["slabsData"]):
                if index in self.create_errors:
                    out.append(deepcopy(self.create_errors[index]))
                    continue
                guid = str(uuid4()).upper()
                self.elements[guid] = "Slab"
                row = deepcopy(CREATE_SLABS_FIXTURE["slab_details"])
                row["floorIndex"] = slab["floorIndex"]
                floor = next(s for s in self.stories if s["index"] == slab["floorIndex"])
                points = deepcopy(slab["polygonCoordinates"])
                row["details"].update(
                    thickness=slab["thickness"],
                    level=slab["level"] - floor["level"],
                    zCoordinate=slab["level"],
                    referencePlaneLocation=slab["referencePlaneLocation"],
                    polygonOutline=points + [deepcopy(points[0])],
                    holes=deepcopy(slab["holes"]),
                )
                self.details[guid] = row
                out.append(self._id(guid))
            return ok({"addOnCommandResponse": {"elements": out}})
        if name == "CreateWalls":
            out = []
            for index, wall in enumerate(args["wallsData"]):
                if index in self.create_errors:
                    out.append(deepcopy(self.create_errors[index]))
                    continue
                guid = str(uuid4()).upper()
                self.elements[guid] = "Wall"
                row = deepcopy(CREATE_WALLS_FIXTURE["wall_details"])
                row["floorIndex"] = wall["floorIndex"]
                floor = next(s for s in self.stories if s["index"] == wall["floorIndex"])
                row["details"].update(
                    begCoordinate=wall["begCoordinate"],
                    endCoordinate=wall["endCoordinate"],
                    height=wall["height"],
                    begThickness=wall["thickness"],
                    endThickness=wall["thickness"],
                    bottomOffset=wall["zCoordinate"],
                    zCoordinate=floor["level"] + wall["zCoordinate"],
                    offset=wall["offset"],
                    referenceLineLocation=wall["referenceLineLocation"],
                )
                self.details[guid] = row
                out.append(self._id(guid))
            return ok({"addOnCommandResponse": {"elements": out}})
        return ok({"addOnCommandResponse": {"error": {"code": 1, "message": f"Unknown {name}"}}})

    def _floor(self, z: float) -> tuple[int, float]:
        """Tapir's GetFloorIndexAndOffset: the highest story at or below z."""
        found = None
        for story in sorted(self.stories, key=lambda s: s["index"]):
            if story["level"] > z:
                break
            found = story
        return (found["index"], z - found["level"]) if found else (0, z)

    def _modify(self, name: str, args: dict) -> dict:
        kind, key = MODIFY_COMMANDS[name]
        rows = []
        for index, entry in enumerate(args[key]):
            guid = entry["elementId"]["guid"]
            if index in self.modify_errors:
                rows.append(deepcopy(self.modify_errors[index]))
                continue
            if self.elements.get(guid) != kind or guid in self.locked_elements:
                rows.append(deepcopy(MODIFY_ELEMENTS_FIXTURE["failures"][name]))
                continue
            if not self.modify_ignored:
                row = self.details[guid]
                details = row["details"]
                story = next(s for s in self.stories if s["index"] == row["floorIndex"])
                changes = {k: deepcopy(v) for k, v in entry.items() if k != "elementId"}
                if "zCoordinate" in changes:  # slabs: absolute, Tapir picks the story
                    z = changes.pop("zCoordinate")
                    row["floorIndex"], details["level"] = self._floor(z)
                    details["zCoordinate"] = z
                if "coordinates" in changes:  # objects: absolute, Tapir picks the story
                    coordinates = changes.pop("coordinates")
                    row["floorIndex"], _ = self._floor(coordinates["z"])
                    details["origin"] = coordinates
                if name == "ModifyColumns" and "bottomOffset" in changes:
                    details["zCoordinate"] = story["level"] + changes["bottomOffset"]
                if name == "ModifyColumns" and "height" in changes:
                    details["relativeTopStory"] = 0
                if name == "ModifyBeams" and "level" in changes:
                    details["zCoordinate"] = story["level"] + changes["level"]
                details.update(changes)
            rows.append(deepcopy(MODIFY_ELEMENTS_FIXTURE["success"]))
        return ok({"addOnCommandResponse": {"executionResults": rows}})

    @staticmethod
    def _id(guid: str) -> dict:
        return {"elementId": {"guid": guid}}


def fake_transport(*instances: FakeArchicad) -> httpx.MockTransport:
    by_port = {i.port: i for i in instances}

    def handler(request: httpx.Request) -> httpx.Response:
        instance = by_port.get(request.url.port)
        if instance is None:
            raise httpx.ConnectError("Connection refused", request=request)
        body = json.loads(request.content)
        response = instance.handle(body)
        command = body.get("parameters", {}).get("addOnCommandId", {}).get("commandName")
        if instance.lose_create_response and command == "CreateWalls":
            raise httpx.ReadTimeout("Injected lost response after model change", request=request)
        if instance.lose_slab_response and command == "CreateSlabs":
            raise httpx.ReadTimeout(
                "Injected lost slab response after model change", request=request
            )
        if instance.lose_delete_response and command == "DeleteElements":
            raise httpx.ReadTimeout(
                "Injected lost deletion response after model change", request=request
            )
        if instance.lose_modify_wall_response and command == "ModifyWalls":
            raise httpx.ReadTimeout(
                "Injected lost wall-edit response after model change", request=request
            )
        if instance.lose_modify_response and command in MODIFY_COMMANDS:
            raise httpx.ReadTimeout(
                "Injected lost element-edit response after model change", request=request
            )
        if instance.lose_gdl_response and command == "SetGDLParametersOfElements":
            raise httpx.ReadTimeout(
                "Injected lost GDL response after model change", request=request
            )
        if instance.lose_rotate_response and command == "RotateElements":
            raise httpx.ReadTimeout(
                "Injected lost rotation response after model change", request=request
            )
        if instance.lose_move_response and command == "MoveElements":
            raise httpx.ReadTimeout(
                "Injected lost move response after model change", request=request
            )
        if instance.lose_opening_response and command in ("CreateWindows", "CreateDoors"):
            raise httpx.ReadTimeout("lost opening response", request=request)
        if instance.lose_object_response and command == "CreateObjects":
            raise httpx.ReadTimeout(
                "Injected lost object response after model change", request=request
            )
        if instance.lose_zone_response and command == "CreateZones":
            raise httpx.ReadTimeout(
                "Injected lost zone response after model change", request=request
            )
        if instance.lose_beam_response and command == "CreateBeams":
            raise httpx.ReadTimeout(
                "Injected lost beam response after model change", request=request
            )
        if instance.lose_column_response and command == "CreateColumns":
            raise httpx.ReadTimeout(
                "Injected lost column response after model change", request=request
            )
        return httpx.Response(200, json=response)

    return httpx.MockTransport(handler)
