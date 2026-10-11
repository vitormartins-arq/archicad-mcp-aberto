"""A fake Archicad that answers like the JSON API, for tests without Archicad.

Each FakeArchicad stands for one running instance on one port. `fake_transport`
routes requests by port; ports with no instance refuse the connection, like a
real machine.
"""

from __future__ import annotations

import json
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
    cut_fills: dict[str, list] = field(default_factory=dict)  # guid -> polygons
    calls: list[str] = field(default_factory=list)
    tapir_calls: list[str] = field(default_factory=list)
    tapir_requests: list[dict] = field(default_factory=list)

    def handle(self, body: dict) -> dict:
        command = body.get("command", "")
        params = body.get("parameters", {})
        self.calls.append(command)
        if self.busy:
            return fail(4001, "Invalid program status (ongoing user input)")
        if command == "API.GetProductInfo":
            return ok(
                {"version": self.version, "buildNumber": self.build, "languageCode": self.language}
            )
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
                out.append({"propertyDefinition": {"guid": g, "name": self.properties[g]}})
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
                                {"propertyValue": {"value": "x"}} for _ in params["properties"]
                            ]
                        }
                    )
            return ok({"propertyValuesForElements": rows})
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
        return httpx.Response(200, json=response)

    return httpx.MockTransport(handler)
