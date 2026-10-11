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
from uuid import uuid4

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
    lose_slab_response: bool = False
    lose_column_response: bool = False
    lose_object_response: bool = False
    # Library part names CreateObjects can find; any other name fails that item.
    library_parts: set[str] = field(default_factory=lambda: {"Mesa Retangular 30"})
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
                        "isUntitled": False,
                        "isTeamwork": False,
                        "projectName": self.project_name,
                    }
                }
            )
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
        if instance.lose_move_response and command == "MoveElements":
            raise httpx.ReadTimeout(
                "Injected lost move response after model change", request=request
            )
        if instance.lose_object_response and command == "CreateObjects":
            raise httpx.ReadTimeout(
                "Injected lost object response after model change", request=request
            )
        if instance.lose_column_response and command == "CreateColumns":
            raise httpx.ReadTimeout(
                "Injected lost column response after model change", request=request
            )
        return httpx.Response(200, json=response)

    return httpx.MockTransport(handler)
