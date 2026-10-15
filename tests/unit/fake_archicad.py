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
    "ModifyRoofs": ("Roof", "roofsWithDetails"),
    "ModifyTexts": ("Text", "textsWithDetails"),
    "ModifyLabels": ("Label", "labelsWithDetails"),
    "ModifyMeshes": ("Mesh", "meshesData"),
}


# Official classification commands, from the archicad 30.3000 package; not live.
CLASSIFICATIONS_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "ac30_classifications_documented.json").read_text(
        encoding="utf-8"
    )
)
# 2D drafting (lines, polylines, arcs, circles, hatches), from the Tapir 1.7.0 source.
DRAFTING_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "tapir170_drafting_documented.json").read_text(
        encoding="utf-8"
    )
)
# name -> (element type, list key)
LAYERS_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "tapir170_layers_create_documented.json").read_text(
        encoding="utf-8"
    )
)


SELECTION_FIXTURE = json.loads(
    (
        Path(__file__).parents[1] / "fixtures" / "tapir170_selection_groups_documented.json"
    ).read_text(encoding="utf-8")
)


PROJECT_INFO_FIXTURE = json.loads(
    (
        Path(__file__).parents[1] / "fixtures" / "tapir170_project_info_favorites_documented.json"
    ).read_text(encoding="utf-8")
)

# LockElements, UnlockElements and UpdateZones; source-derived, not live captured.
LOCKS_ZONES_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "tapir170_locks_zones_documented.json").read_text(
        encoding="utf-8"
    )
)
# GetAllProperties, CreatePropertyGroups, CreatePropertyDefinitions; not live captured.
PROPERTY_DEFINITIONS_FIXTURE = json.loads(
    (
        Path(__file__).parents[1] / "fixtures" / "tapir170_property_definitions_documented.json"
    ).read_text(encoding="utf-8")
)
# Navigator trees and new worksheets, details and layouts; not live captured.
DOCUMENTS_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "tapir170_documents_documented.json").read_text(
        encoding="utf-8"
    )
)
# Tapir type -> (propertyCollectionType, propertyValueType, propertyMeasureType), as
# PropertyTypeDictionary in PropertyCommands.cpp sets them.
PROPERTY_TYPES = {
    "number": ("Single", "Real", "Default"),
    "integer": ("Single", "Integer", "Default"),
    "string": ("Single", "String", "Default"),
    "boolean": ("Single", "Boolean", "Default"),
    "length": ("Single", "Real", "Length"),
    "area": ("Single", "Real", "Area"),
    "volume": ("Single", "Real", "Volume"),
    "angle": ("Single", "Real", "Angle"),
    "numberList": ("List", "Real", "Default"),
    "integerList": ("List", "Integer", "Default"),
    "stringList": ("List", "String", "Default"),
    "booleanList": ("List", "Boolean", "Default"),
    "lengthList": ("List", "Real", "Length"),
    "areaList": ("List", "Real", "Area"),
    "volumeList": ("List", "Real", "Volume"),
    "angleList": ("List", "Real", "Angle"),
    "singleEnum": ("SingleChoiceEnumeration", "String", "Default"),
    "multiEnum": ("MultipleChoiceEnumeration", "String", "Default"),
}


def layer_guid(index: int) -> str:
    return f"44444444-4444-4444-8444-{index:012d}"


def surface_guid(index: int) -> str:
    return f"45454545-4545-4545-8545-{index:012d}"


def combination_guid(index: int) -> str:
    return f"47474747-4747-4747-8747-{index:012d}"


def folder_guid(index: int) -> str:
    return f"48484848-4848-4848-8848-{index:012d}"


# Layer folders as API.GetAttributeFolderStructure returns them (official AC30 schema from
# the archicad 30.3000 package; not live captured).
def _folder(index: int, name: str, *subfolders: dict) -> dict:
    tree: dict = {"attributeFolderId": {"guid": folder_guid(index)}, "name": name}
    tree["attributes"] = []
    if subfolders:
        tree["subfolders"] = [{"attributeFolder": f} for f in subfolders]
    return tree


LAYER_FOLDERS = _folder(
    0,
    "Camadas",
    _folder(1, "ANOTAÇÃO"),
    _folder(2, "ARQUITETURA", _folder(3, "ANT - Antigo")),
    _folder(4, "ESTRUTURA"),
)


# Rename commands of rename_items, from the Tapir 1.7.0 source; not live captured.
RENAME_COMMANDS = {
    "RenameNavigatorItem",
    "RenameFavorites",
    "UpdateClassificationSystems",
    "UpdateClassificationItems",
    "UpdatePropertyGroups",
    "UpdatePropertyDefinitions",
}
RENAME_OVERWRITES = (
    "CreateLayers",
    "CreateBuildingMaterials",
    "CreateSurfaces",
    "CreateLayerCombinations",
)


DRAFTING_COMMANDS = {
    "CreateLineElements": ("Line", "linesData"),
    "CreatePolylines": ("PolyLine", "polylinesData"),
    "CreateArcs": ("Arc", "arcsData"),
    "CreateCircles": ("Circle", "circlesData"),
    "CreateHatches": ("Hatch", "hatchesData"),
}
# CreateLabels and the Label details, from the Tapir 1.7.0 source; not live.
LABELS_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "tapir170_create_labels_documented.json").read_text(
        encoding="utf-8"
    )
)


# CreateRoofs/CreateTexts and their details, from the Tapir 1.7.0 source; not live.
ROOFS_TEXTS_FIXTURE = json.loads(
    (
        Path(__file__).parents[1] / "fixtures" / "tapir170_create_roofs_texts_documented.json"
    ).read_text(encoding="utf-8")
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
    surfaces: dict[int, str] = field(
        default_factory=lambda: {1: "Pintura Branca", 2: "Concreto Aparente"}
    )
    classification_data: dict = field(default_factory=lambda: deepcopy(CLASSIFICATIONS_FIXTURE))
    # Renames (rename_items): refuse items by position, answer success without renaming,
    # or lose the answer after renaming.
    rename_errors: dict[int, dict] = field(default_factory=dict)
    rename_ignored: bool = False
    lose_rename_response: bool = False
    # Archicad refuses the whole rename call (succeeded: false), as for a schema error.
    rename_call_refused: bool = False
    # index -> {"name", "layers": {layer index: state overrides}}; GetLayerCombinations and
    # CreateLayerCombinations from the Tapir 1.7.0 source, not live captured.
    layer_combinations: dict[int, dict] = field(
        default_factory=lambda: {
            1: {"name": "0ª ETAPA | (3D) ARCHICAD", "layers": {}},
            2: {"name": "1ª ETAPA | CADASTRO", "layers": {1: {"isHidden": True}}},
        }
    )
    # Simulate an Archicad that resets layer states when a combination is renamed.
    combination_reset_on_rename: bool = False
    attribute_folders: dict[str, dict] = field(
        default_factory=lambda: {"Layer": deepcopy(LAYER_FOLDERS)}
    )
    layers: dict[int, str | None] = field(default_factory=lambda: {1: "Walls"})
    # layer index -> {"isHidden", "isLocked", "isWireframe", "intersectionGroupNr"}
    layer_flags: dict[int, dict] = field(default_factory=dict)
    layer_create_errors: dict[int, dict] = field(default_factory=dict)
    layer_move_errors: dict[int, dict] = field(default_factory=dict)
    layer_move_ignored: bool = False
    lose_layer_response: bool = False
    # group guid -> member element guids; highlight is the last HighlightElements request.
    groups: dict[str, list[str]] = field(default_factory=dict)
    group_create_errors: dict[int, dict] = field(default_factory=dict)
    lose_group_response: bool = False
    select_refused: set[str] = field(default_factory=set)
    highlight: dict | None = None
    project_info: list[dict] = field(
        default_factory=lambda: deepcopy(PROJECT_INFO_FIXTURE["fields"])
    )
    project_info_refused: set[str] = field(default_factory=set)
    project_info_ignored: bool = False
    lose_project_info_response: bool = False
    # element guid -> favorite names applied, in order
    applied_favorites: dict[str, list[str]] = field(default_factory=dict)
    favorite_layers: dict[str, int] = field(default_factory=dict)  # favorite -> layer index
    lose_favorite_response: bool = False
    # LockElements/UnlockElements: refuse the whole batch, answer success without
    # changing anything, or lose the answer after acting.
    property_groups: list[dict] = field(
        default_factory=lambda: deepcopy(PROPERTY_DEFINITIONS_FIXTURE["propertyGroups"])
    )
    custom_properties: list[dict] = field(
        default_factory=lambda: deepcopy(PROPERTY_DEFINITIONS_FIXTURE["properties"])
    )
    property_group_errors: dict[int, dict] = field(default_factory=dict)
    property_create_errors: dict[int, dict] = field(default_factory=dict)
    property_drops_availability: bool = False  # store without availability (mismatch test)
    lose_property_definition_response: bool = False
    navigator_trees: dict[str, dict] = field(
        default_factory=lambda: deepcopy(DOCUMENTS_FIXTURE["trees"])
    )
    # navigator item guid -> database guid
    nav_databases: dict[str, str] = field(
        default_factory=lambda: dict(DOCUMENTS_FIXTURE["databases"])
    )
    document_errors: dict[int, dict] = field(default_factory=dict)
    document_stored_name: str | None = None  # store this name instead (mismatch test)
    lose_document_response: bool = False
    lock_refused: bool = False
    lock_ignored: bool = False
    lose_lock_response: bool = False
    # UpdateZones requests received, and how the next one answers.
    zone_updates: list[dict] = field(default_factory=list)
    zone_update_refused: bool = False
    lose_zone_update_response: bool = False
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
    lose_roof_response: bool = False
    # Roof tool default; a Composite default keeps its own thickness (0.30 m live, 13/10).
    roof_default_structure: str = "Basic"
    lose_text_response: bool = False
    lose_label_response: bool = False
    lose_drafting_response: bool = False
    # Shift every created 2D box by this much in x (verification tests).
    drafting_coordinate_shift: float = 0.0
    # Archicad stores what it is given unless told otherwise (verification tests).
    text_stored_as: str | None = None
    # (element guid, system guid) -> item guid; a missing pair is unclassified.
    classifications: dict[tuple[str, str], str] = field(default_factory=dict)
    classification_set_errors: dict[int, dict] = field(default_factory=dict)
    classification_ignored: bool = False
    lose_classification_response: bool = False
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

    # IssueCommands.cpp tag 1.7.0; source-derived, not captured live.
    issues: dict[str, dict] = field(
        default_factory=lambda: {
            r["issueId"]["guid"]: deepcopy(r) for r in ISSUES_FIXTURE["get_issues"]["issues"]
        }
    )
    issue_attachments: dict[str, set[str]] = field(default_factory=dict)
    issue_errors: dict[str, dict[int, dict]] = field(default_factory=dict)
    issue_ignored: set[str] = field(default_factory=set)
    lose_issue_response_at: int | None = None

    publisher_sets: dict[str, dict] = field(
        default_factory=lambda: deepcopy(NAVIGATOR_FIXTURE["publisher_sets"])
    )

    lose_mesh_response: bool = False
    mesh_base_shift: float = 0.0
    morph_box_shift: float = 0.0
    dimension_floor_shift: int = 0

    view_settings: dict[str, dict] = field(
        default_factory=lambda: deepcopy(VIEW_SETTINGS_FIXTURE["views"])
    )
    view_settings_errors: dict[int, dict] = field(default_factory=dict)
    view_settings_ignored: bool = False
    view_settings_reset_pen_set: bool = False
    view_settings_change_layers: bool = False
    lose_view_settings_response: bool = False

    layer_settings_errors: dict[int, dict] = field(default_factory=dict)
    layer_settings_ignored: bool = False
    lose_layer_settings_response: bool = False
    layer_combination_read_errors: dict[int, dict] = field(default_factory=dict)
    section_stored_name: str | None = None  # Project Map shows this name instead
    section_wrong_floor: bool = False
    lose_section_response: bool = False
    # CreateFavoritesFromElements: names Archicad refuses, and a name listed back instead.
    favorite_create_refused: set[str] = field(default_factory=set)
    favorite_stored_name: str | None = None
    created_favorites: list[dict] = field(default_factory=list)
    lose_favorite_create_response: bool = False
    # Attribute property values as display text, keyed by (attribute guid, property guid).
    attribute_property_values: dict[tuple[str, str], str] = field(default_factory=dict)
    attribute_property_refused: set[str] = field(default_factory=set)  # values refused
    attribute_property_stored: str | None = None  # Archicad keeps this text instead
    lose_attribute_property_response: bool = False
    # Keynote tree in GetKeynoteTree shape (Tapir 1.7.0 source; not live captured).
    keynotes: dict = field(default_factory=lambda: {"foldersInRoot": [], "itemsInRoot": []})
    keynote_stored_title: str | None = None  # Archicad keeps this title instead
    lose_keynote_response: bool = False

    def __post_init__(self):
        # Preserve the existing ProjectMap/LayoutBook fake and add the two other maps.
        for map_id, tree in NAVIGATOR_FIXTURE["trees"].items():
            self.navigator_trees.setdefault(map_id, deepcopy(tree))

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
        if command == "API.GetAttributeFolderStructure":
            tree = self.attribute_folders.get(params["attributeType"])
            if tree is None:
                return fail(-2130313112, "No folders for this attribute type")
            return ok({"attributeFolder": deepcopy(tree)})
        if command == "API.RenameAttributeFolders":
            results = []
            for position, row in enumerate(params["attributeFolderParametersList"]):
                guid = row["attributeFolderId"]["guid"]
                stack = list(self.attribute_folders.values())
                folder = None
                while stack and folder is None:
                    node = stack.pop()
                    if node["attributeFolderId"]["guid"] == guid:
                        folder = node
                    stack += [c["attributeFolder"] for c in node.get("subfolders", [])]
                if position in self.rename_errors or folder is None:
                    error = self.rename_errors.get(position, {"code": -1, "message": "Failed."})
                    results.append({"success": False, "error": deepcopy(error)})
                    continue
                if not self.rename_ignored:
                    folder["name"] = row["newName"]
                results.append({"success": True})
            return ok({"executionResults": results})
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
                if g not in self.properties:
                    # Error row shape assumed from the JSON API docs; not live captured.
                    out.append({"error": {"code": 4006, "message": "Property not found"}})
                    continue
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
        if command == "API.GetAllClassificationSystems":
            return ok(deepcopy(self.classification_data["systems"]))
        if command == "API.GetAllClassificationsInSystem":
            tree = self.classification_data["items"].get(params["classificationSystemId"]["guid"])
            if tree is None:
                return fail(4013, "Classification system not found")
            return ok(deepcopy(tree))
        if command == "API.GetClassificationsOfElements":
            rows = []
            for e in params["elements"]:
                g = e["elementId"]["guid"]
                if g not in self.elements:
                    rows.append(deepcopy(CLASSIFICATIONS_FIXTURE["element_error"]))
                    continue
                ids = []
                for s in params["classificationSystemIds"]:
                    system = s["classificationSystemId"]["guid"]
                    identifier = {"classificationSystemId": {"guid": system}}
                    if (g, system) in self.classifications:
                        identifier["classificationItemId"] = {
                            "guid": self.classifications[(g, system)]
                        }
                    ids.append({"classificationId": identifier})
                rows.append({"classificationIds": ids})
            return ok({"elementClassifications": rows})
        if command == "API.SetClassificationsOfElements":
            results = []
            for index, entry in enumerate(params["elementClassifications"]):
                g = entry["elementId"]["guid"]
                identifier = entry["classificationId"]
                system = identifier["classificationSystemId"]["guid"]
                if index in self.classification_set_errors:
                    results.append(deepcopy(self.classification_set_errors[index]))
                elif g not in self.elements:
                    results.append(
                        {"success": False, **deepcopy(CLASSIFICATIONS_FIXTURE["element_error"])}
                    )
                else:
                    if not self.classification_ignored:
                        if "classificationItemId" in identifier:
                            item = identifier["classificationItemId"]["guid"]
                            self.classifications[(g, system)] = item
                        else:
                            self.classifications.pop((g, system), None)
                    results.append({"success": True})
            return ok({"executionResults": results})
        if command == "API.ExecuteAddOnCommand":
            return self._tapir(params)
        return fail(4000, f"Unknown command {command}")

    def _keynote_folder(self, guid: str | None) -> dict | None:
        """The folder row with this GUID, the root for None, or None when missing."""
        if guid is None:
            return self.keynotes
        stack = list(self.keynotes["foldersInRoot"])
        while stack:
            row = stack.pop()
            if row["keynoteFolderId"]["guid"] == guid:
                return row
            stack.extend(row["subFolders"])
        return None

    def _nav_items(self, map_id: str) -> list[dict]:
        out, stack = [], [self.navigator_trees[map_id]]
        while stack:
            node = stack.pop()
            out.append(node)
            stack += [c["navigatorItem"] for c in reversed(node.get("children", []))]
        return out  # depth first, in tree order

    def _create_documents(self, name: str, args: dict) -> list[dict]:
        key, kind, map_id = {
            "CreateWorksheets": ("worksheetsData", "WorksheetDrawingItem", "ProjectMap"),
            "CreateDetails": ("detailsData", "DetailDrawingItem", "ProjectMap"),
            "CreateLayout": ("layoutsData", "LayoutItem", "LayoutBook"),
        }[name]
        out = []
        for position, data in enumerate(args[key]):
            if position in self.document_errors:
                out.append(deepcopy(self.document_errors[position]))
                continue
            if name == "CreateLayout":
                # The MCP always names the master by navigator ID, never by name.
                assert "masterLayoutName" not in data
                master = data["masterNavigatorItemId"]["guid"]
                masters = [
                    n["navigatorItemId"]["guid"]
                    for n in self._nav_items("LayoutBook")
                    if n["type"] == "MasterLayoutItem"
                ]
                if master not in masters:
                    out.append(deepcopy(DOCUMENTS_FIXTURE["layout_failed"]))
                    continue
            nav, database = str(uuid4()).upper(), str(uuid4()).upper()
            self.navigator_trees[map_id].setdefault("children", []).append(
                {
                    "navigatorItem": {
                        "navigatorItemId": {"guid": nav},
                        "type": kind,
                        "name": self.document_stored_name
                        or data.get("name", data.get("layoutName")),
                        "prefix": "",
                        "uiId": data.get("referenceId", ""),
                        "customUiId": False,
                        "customName": False,
                        "isIndependent": name != "CreateLayout",
                    }
                }
            )
            self.nav_databases[nav] = database
            out.append({"databaseId": {"guid": database}})
        return out

    def _create_property(self, definition: dict) -> dict:
        # Like Tapir 1.7.0: the schema requires these keys; a missing group fails the item.
        assert {"name", "description", "type", "isEditable", "availability", "group"} <= set(
            definition
        )
        group_guid = definition["group"]["propertyGroupId"]["guid"]
        group = next(
            (g for g in self.property_groups if g["propertyGroupId"]["guid"] == group_guid), None
        )
        if group is None:
            return deepcopy(PROPERTY_DEFINITIONS_FIXTURE["property_failed"])
        collection, value_type, measure = PROPERTY_TYPES[definition["type"]]
        options = [
            {
                "enumValue": {
                    "displayValue": e["enumValue"]["displayValue"],
                    "guid": str(uuid4()).upper(),
                }
            }
            for e in definition.get("possibleEnumValues", [])
        ]
        guid = str(uuid4()).upper()
        row = {
            "propertyId": {"guid": guid},
            "propertyType": "Custom",
            "propertyGroupName": group["name"],
            "propertyName": definition["name"],
            "propertyCollectionType": collection,
            "propertyValueType": value_type,
            "propertyMeasureType": measure,
            "propertyIsEditable": definition["isEditable"],
            "isExpressionBased": False,
            "propertyGroupId": {"guid": group_guid},
            "propertyDescription": definition["description"],
            "availability": []
            if self.property_drops_availability
            else deepcopy(definition["availability"]),
        }
        if options:
            row["possibleEnumValues"] = options
        default = definition.get("defaultValue", {}).get("basicDefaultValue")
        if default:
            value = default["value"]
            if definition["type"] in ("singleEnum", "multiEnum"):
                ids = value if isinstance(value, list) else [{"enumValueId": value}]
                names = [i["enumValueId"]["displayValue"] for i in ids]
                chosen = [o for o in options if o["enumValue"]["displayValue"] in names]
                row["defaultEnumValueIds"] = [{"guid": o["enumValue"]["guid"]} for o in chosen]
                row["defaultValueDisplay"] = "; ".join(names)
            else:
                row["defaultValueDisplay"] = str(value)
        self.custom_properties.append(row)
        return {"propertyId": {"guid": guid}}

    def _on_locked_layer(self, guid: str) -> bool:
        layer = self.details.get(guid, {}).get("layerIndex")
        return self.layer_flags.get(layer, {}).get("isLocked") is True

    def _issues(self, name: str, args: dict) -> dict:
        if name == "GetIssues":
            return ok({"addOnCommandResponse": {"issues": list(deepcopy(self.issues).values())}})
        guid = args.get("issueId", {}).get("guid")
        if name == "GetElementsAttachedToIssue":
            if guid not in self.issues:
                return ok(
                    {
                        "addOnCommandResponse": {
                            "error": {
                                "code": -1,
                                "message": "Failed to retrieve attached elements.",
                            }
                        }
                    }
                )
            assert args["type"] == "Highlight"
            return ok(
                {
                    "addOnCommandResponse": {
                        "elements": [
                            self._id(g) for g in sorted(self.issue_attachments.get(guid, set()))
                        ]
                    }
                }
            )
        position = self.tapir_calls.count(name) - 1
        error = self.issue_errors.get(name, {}).get(position)
        if error is not None:
            return ok({"addOnCommandResponse": deepcopy(error)})
        if name == "CreateIssue":
            new_guid = str(uuid4()).upper()
            if name not in self.issue_ignored:
                row = deepcopy(ISSUES_FIXTURE["get_issues"]["issues"][0])
                row.update(
                    issueId={"guid": new_guid}, name=args["name"], tagText=args.get("tagText", "")
                )
                self.issues[new_guid] = row
            return ok({"addOnCommandResponse": {"issueId": {"guid": new_guid}}})
        assert name == "AttachElementsToIssue" and args["type"] == "Highlight"
        guids = [r["elementId"]["guid"] for r in args["elements"]]
        if guid not in self.issues or any(g not in self.elements for g in guids):
            return ok({"addOnCommandResponse": deepcopy(ISSUES_FIXTURE["attach_error"])})
        if name not in self.issue_ignored:
            self.issue_attachments.setdefault(guid, set()).update(guids)
        return ok({"addOnCommandResponse": deepcopy(ISSUES_FIXTURE["attach_elements"])})

    def _tapir(self, params: dict) -> dict:
        if self.tapir_version is None:
            return fail(4010, "Add-On command is not registered")
        name = params["addOnCommandId"]["commandName"]
        args = params.get("addOnCommandParameters", {})
        self.tapir_calls.append(name)
        self.tapir_requests.append({"command": name, "parameters": deepcopy(args)})
        if name in (
            "GetIssues",
            "CreateIssue",
            "AttachElementsToIssue",
            "GetElementsAttachedToIssue",
        ):
            return self._issues(name, args)

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
                {
                    **deepcopy(fixture["attributes"][0]),
                    "attributeId": {"guid": layer_guid(index)},
                    "index": index,
                    "name": name,
                }
                for index, name in self.layers.items()
            ]
            return ok({"addOnCommandResponse": {"attributes": rows}})
        if name == "GetProjectInfoFields":
            return ok({"addOnCommandResponse": {"fields": deepcopy(self.project_info)}})
        if name == "SetProjectInfoField":
            key = args["projectInfoId"]
            row = next((r for r in self.project_info if r["projectInfoId"] == key), None)
            if row is None or key in self.project_info_refused:
                error = deepcopy(PROJECT_INFO_FIXTURE["set_error"])
                return ok({"addOnCommandResponse": {"error": error}})
            if not self.project_info_ignored:
                row["projectInfoValue"] = args["projectInfoValue"]
            return ok({"addOnCommandResponse": {}})
        if name == "ApplyFavoritesToElements":
            assert set(args) == {"favoritesToApply"}
            out = []
            for row in args["favoritesToApply"]:
                guid, favorite = row["elementId"]["guid"], row["favorite"]
                kind = self.elements.get(guid)
                if kind is None:
                    out.append(deepcopy(PROJECT_INFO_FIXTURE["apply_no_favorite"]))
                elif favorite not in self.favorites.get(kind, []):
                    known = any(favorite in names for names in self.favorites.values())
                    fixture = "apply_type_mismatch" if known else "apply_no_favorite"
                    out.append(deepcopy(PROJECT_INFO_FIXTURE[fixture]))
                else:
                    self.applied_favorites.setdefault(guid, []).append(favorite)
                    if favorite in self.favorite_layers and guid in self.details:
                        self.details[guid]["layerIndex"] = self.favorite_layers[favorite]
                    out.append(deepcopy(PROJECT_INFO_FIXTURE["apply_ok"]))
            return ok({"addOnCommandResponse": {"executionResults": out}})
        if name == "GetKeynoteTree":
            # Shapes from the Tapir 1.7.0 source (KeynoteCommands.cpp); not live captured.
            return ok({"addOnCommandResponse": deepcopy(self.keynotes)})
        if name in ("CreateKeynoteFolders", "CreateKeynoteItems"):
            folder = name == "CreateKeynoteFolders"
            key, answer = (
                ("foldersData", "keynoteFolderIdsOrErrors")
                if folder
                else (
                    "itemsData",
                    "keynoteItemIdsOrErrors",
                )
            )
            assert set(args) == {key}
            out = []
            for index, data in enumerate(args[key]):
                allowed = {"parentFolderId", "key", "title"}
                assert set(data) <= (allowed if folder else allowed | {"description", "reference"})
                parent = self._keynote_folder(data.get("parentFolderId", {}).get("guid"))
                if index in self.create_errors or parent is None:
                    message = "Failed to find the parent folder."
                    error = {"code": -2130313112, "message": message}
                    out.append(deepcopy(self.create_errors.get(index, {"error": error})))
                    continue
                guid = str(uuid4()).upper()
                title = self.keynote_stored_title or data.get("title", "")
                row = {"key": data["key"], "title": title, "reference": data.get("reference", "")}
                row["uiText"] = f"{data['key']} {title}".strip()
                if folder:
                    row = {"keynoteFolderId": {"guid": guid}, **row, "subFolders": [], "items": []}
                    parent["subFolders" if "subFolders" in parent else "foldersInRoot"].append(row)
                else:
                    row = {"keynoteItemId": {"guid": guid}, **row}
                    row["description"] = data.get("description", "")
                    parent["items" if "items" in parent else "itemsInRoot"].append(row)
                out.append({"keynoteFolderId" if folder else "keynoteItemId": {"guid": guid}})
            return ok({"addOnCommandResponse": {answer: out}})
        if name == "GetPropertyValuesOfAttributes":
            # Shapes from the Tapir 1.7.0 source (PropertyCommands.cpp); not live captured.
            assert set(args) == {"attributeIds", "properties"}
            out = []
            for attribute in args["attributeIds"]:
                values = []
                for prop in args["properties"]:
                    key = (attribute["attributeId"]["guid"], prop["propertyId"]["guid"])
                    if key in self.attribute_property_values:
                        text = self.attribute_property_values[key]
                        values.append({"propertyValue": {"value": text}})
                    else:
                        message = "Not available or not evaluated property"
                        values.append({"error": {"code": -2130312312, "message": message}})
                out.append({"propertyValues": values})
            return ok({"addOnCommandResponse": {"propertyValuesForAttributes": out}})
        if name == "SetPropertyValuesOfAttributes":
            # Shapes from the Tapir 1.7.0 source (PropertyCommands.cpp); not live captured.
            assert set(args) == {"attributePropertyValues"}
            out = []
            for row in args["attributePropertyValues"]:
                assert set(row) == {"attributeId", "propertyId", "propertyValue"}
                key = (row["attributeId"]["guid"], row["propertyId"]["guid"])
                text = row["propertyValue"]["value"]
                if key not in self.attribute_property_values or text in (
                    self.attribute_property_refused
                ):
                    message = "Failed to set property value for attribute"
                    out.append(
                        {"success": False, "error": {"code": -2130313112, "message": message}}
                    )
                else:
                    self.attribute_property_values[key] = self.attribute_property_stored or text
                    out.append({"success": True})
            return ok({"addOnCommandResponse": {"executionResults": out}})
        if name == "CreateFavoritesFromElements":
            # Shapes from the Tapir 1.7.0 source (FavoritesCommands.cpp); not live captured.
            assert set(args) == {"favoritesFromElements"}
            out = []
            for row in args["favoritesFromElements"]:
                assert set(row) <= {"elementId", "favorite", "folder"}
                kind = self.elements.get(row["elementId"]["guid"])
                if kind is None:
                    error = {"code": -2130313112, "message": "Failed to find element"}
                    out.append({"success": False, "error": error})
                elif row["favorite"] in self.favorite_create_refused:
                    error = {"code": -2130313112, "message": "Failed to create the favorite"}
                    out.append({"success": False, "error": error})
                else:
                    stored = self.favorite_stored_name or row["favorite"]
                    self.favorites.setdefault(kind, []).append(stored)
                    self.created_favorites.append(deepcopy(row))
                    out.append({"success": True})
            return ok({"addOnCommandResponse": {"executionResults": out}})
        if name == "ChangeSelectionOfElements":
            added, removed = [], []
            for row in args.get("addElementsToSelection", []):
                guid = row["elementId"]["guid"]
                if guid in self.select_refused or guid not in self.elements:
                    added.append(deepcopy(SELECTION_FIXTURE["select_failed"]))
                    continue
                if guid not in self.selection:
                    self.selection.append(guid)
                added.append(deepcopy(SELECTION_FIXTURE["execution_ok"]))
            for row in args.get("removeElementsFromSelection", []):
                guid = row["elementId"]["guid"]
                if guid in self.selection:
                    self.selection.remove(guid)
                removed.append(deepcopy(SELECTION_FIXTURE["execution_ok"]))
            return ok(
                {
                    "addOnCommandResponse": {
                        "executionResultsOfAddToSelection": added,
                        "executionResultsOfRemoveFromSelection": removed,
                    }
                }
            )
        if name == "HighlightElements":
            self.highlight = deepcopy(args)
            return ok({"addOnCommandResponse": deepcopy(SELECTION_FIXTURE["execution_ok"])})
        if name == "GetGroupsOfElements":
            holder = {m: g for g, members in self.groups.items() for m in members}
            out = [
                {"groupId": {"guid": holder[e["elementId"]["guid"]]}}
                if e["elementId"]["guid"] in holder
                else deepcopy(SELECTION_FIXTURE["not_in_group"])
                for e in args["elements"]
            ]
            return ok({"addOnCommandResponse": {"groupGuids": out}})
        if name == "GetElementsOfGroups":
            out = [
                {"elements": [self._id(m) for m in self.groups[g["groupId"]["guid"]]]}
                if g["groupId"]["guid"] in self.groups
                else deepcopy(SELECTION_FIXTURE["group_missing"])
                for g in args["groups"]
            ]
            return ok({"addOnCommandResponse": {"elementsOfGroups": out}})
        if name == "CreateGroups":
            out = []
            for position, group in enumerate(args["elementGroups"]):
                if position in self.group_create_errors:
                    out.append(deepcopy(self.group_create_errors[position]))
                    continue
                guid = str(uuid4()).upper()
                self.groups[guid] = [e["elementId"]["guid"] for e in group["elements"]]
                out.append({"groupId": {"guid": guid}})
            return ok({"addOnCommandResponse": {"groupGuids": out}})
        if name == "GetViewSettings":
            return ok(
                {
                    "addOnCommandResponse": {
                        "viewSettings": [
                            deepcopy(
                                self.view_settings.get(
                                    r["navigatorItemId"]["guid"],
                                    VIEW_SETTINGS_FIXTURE["not_a_view"],
                                )
                            )
                            for r in args["navigatorItemIds"]
                        ]
                    }
                }
            )
        if name == "SetViewSettings":
            out = []
            for index, entry in enumerate(args["navigatorItemIdsWithViewSettings"]):
                guid = entry["navigatorItemId"]["guid"]
                if index in self.view_settings_errors:
                    out.append(deepcopy(self.view_settings_errors[index]))
                    continue
                if guid not in self.view_settings:
                    out.append(deepcopy(VIEW_SETTINGS_FIXTURE["failed"]))
                    continue
                if not self.view_settings_ignored:
                    self.view_settings[guid].update(deepcopy(entry["viewSettings"]))
                    if self.view_settings_reset_pen_set:
                        self.view_settings[guid]["penSetName"] = "Unexpected side effect"
                    if (
                        self.view_settings_change_layers
                        and "layerCombination" in entry["viewSettings"]
                    ):
                        self.layer_combinations[2]["layers"].setdefault(1, {})["isHidden"] = False
                out.append(deepcopy(VIEW_SETTINGS_FIXTURE["success"]))
            return ok({"addOnCommandResponse": {"executionResults": out}})
        if name == "GetNavigatorItemTree":
            if args["navigatorMapId"] == "PublisherSets" and "publisherSetName" in args:
                tree = self.publisher_sets.get(args["publisherSetName"])
                if tree is None:
                    return ok({"addOnCommandResponse": deepcopy(NAVIGATOR_FIXTURE["invalid_set"])})
                return ok({"addOnCommandResponse": {"navigatorItemTree": deepcopy(tree)}})
            tree = self.navigator_trees.get(args["navigatorMapId"])
            if tree is None:
                return ok({"addOnCommandResponse": {"error": {"code": -1, "message": "No map."}}})
            return ok({"addOnCommandResponse": {"navigatorItemTree": deepcopy(tree)}})
        if name == "GetDatabaseIdFromNavigatorItemId":
            out = []
            for row in args["navigatorItemIds"]:
                database = self.nav_databases.get(row["navigatorItemId"]["guid"])
                if database is None:
                    out.append(deepcopy(DOCUMENTS_FIXTURE["no_database"]))
                else:
                    out.append({"databaseId": {"guid": database}})
            return ok({"addOnCommandResponse": {"databases": out}})
        if name in ("CreateWorksheets", "CreateDetails", "CreateLayout"):
            return ok({"addOnCommandResponse": {"databases": self._create_documents(name, args)}})
        if name == "GetAllProperties":
            return ok(
                {
                    "addOnCommandResponse": {
                        "properties": deepcopy(self.custom_properties),
                        "propertyGroups": deepcopy(self.property_groups),
                    }
                }
            )
        if name == "CreatePropertyGroups":
            out = []
            for position, row in enumerate(args["propertyGroups"]):
                group = row["propertyGroup"]
                taken = any(g["name"] == group["name"] for g in self.property_groups)
                if position in self.property_group_errors or taken:
                    error = self.property_group_errors.get(position)
                    out.append(deepcopy(error or PROPERTY_DEFINITIONS_FIXTURE["group_failed"]))
                    continue
                guid = str(uuid4()).upper()
                self.property_groups.append(
                    {
                        "propertyGroupId": {"guid": guid},
                        "name": group["name"],
                        "description": group.get("description", ""),
                        "isCustom": True,
                    }
                )
                out.append({"propertyGroupId": {"guid": guid}})
            return ok({"addOnCommandResponse": {"propertyGroupIds": out}})
        if name == "CreatePropertyDefinitions":
            out = []
            for position, row in enumerate(args["propertyDefinitions"]):
                if position in self.property_create_errors:
                    out.append(deepcopy(self.property_create_errors[position]))
                    continue
                out.append(self._create_property(row["propertyDefinition"]))
            return ok({"addOnCommandResponse": {"propertyIds": out}})
        if name in ("LockElements", "UnlockElements"):
            guids = [e["elementId"]["guid"] for e in args["elements"]]
            if self.lock_refused or any(g not in self.elements for g in guids):
                key = "lock_failed" if name == "LockElements" else "unlock_failed"
                return ok({"addOnCommandResponse": deepcopy(LOCKS_ZONES_FIXTURE[key])})
            if not self.lock_ignored:
                if name == "LockElements":
                    self.locked_elements.update(guids)
                else:
                    self.locked_elements.difference_update(guids)
            return ok({"addOnCommandResponse": deepcopy(LOCKS_ZONES_FIXTURE["execution_ok"])})
        if name == "UpdateZones":
            if self.zone_update_refused:
                failed = LOCKS_ZONES_FIXTURE["update_zones_failed"]
                return ok({"addOnCommandResponse": deepcopy(failed)})
            self.zone_updates.append(deepcopy(args))
            return ok({"addOnCommandResponse": deepcopy(LOCKS_ZONES_FIXTURE["execution_ok"])})
        if name == "GetLayers":
            by_guid = {layer_guid(i): i for i, n in self.layers.items() if n is not None}
            out = []
            for attribute in args["attributeIds"]:
                index = by_guid.get(attribute["attributeId"]["guid"].upper())
                if index is None:
                    out.append(deepcopy(LAYERS_FIXTURE["get_error"]))
                    continue
                flags = {
                    "isHidden": False,
                    "isLocked": False,
                    "isWireframe": False,
                    "intersectionGroupNr": 1,
                    **self.layer_flags.get(index, {}),
                }
                wanted = args.get("fields", list(flags))
                out.append(
                    {
                        "attributeId": {"guid": layer_guid(index)},
                        "index": index,
                        "name": self.layers[index],
                        **{k: v for k, v in flags.items() if k in wanted},
                    }
                )
            return ok({"addOnCommandResponse": {"layers": out}})
        if (
            name == "CreateLayers"
            and args.get("overwriteExisting") is True
            and any(
                any(
                    key in data
                    for key in ("isHidden", "isLocked", "isWireframe", "intersectionGroupNr")
                )
                for data in args["layerDataArray"]
            )
        ):
            out = []
            for index, data in enumerate(args["layerDataArray"]):
                guid = data["attributeId"]["guid"]
                target = next((i for i in self.layers if layer_guid(i) == guid), None)
                if index in self.layer_settings_errors:
                    out.append(deepcopy(self.layer_settings_errors[index]))
                    continue
                if target is None:
                    # The native generic base can CREATE if the selected attribute vanished.
                    if data["name"] in self.layers.values():
                        out.append(deepcopy(LAYERS_FIXTURE["already_exists"]))
                        continue
                    target = max(self.layers, default=0) + 1
                    self.layers[target] = data["name"]
                if not self.layer_settings_ignored:
                    self.layers[target] = data["name"]
                    self.layer_flags.setdefault(target, {}).update(
                        {
                            k: v
                            for k, v in data.items()
                            if k in ("isHidden", "isLocked", "isWireframe", "intersectionGroupNr")
                        }
                    )
                out.append({"attributeId": {"guid": layer_guid(target)}})
            return ok({"addOnCommandResponse": {"attributeIds": out}})
        if name in RENAME_COMMANDS or (
            name in RENAME_OVERWRITES and args.get("overwriteExisting") is True
        ):
            return self._rename(name, args)
        if name == "CreateLayers":
            assert args.get("overwriteExisting") is False
            out = []
            for position, data in enumerate(args["layerDataArray"]):
                if position in self.layer_create_errors:
                    out.append(deepcopy(self.layer_create_errors[position]))
                elif data["name"] in self.layers.values():
                    out.append(deepcopy(LAYERS_FIXTURE["already_exists"]))
                else:
                    index = max(self.layers, default=0) + 1
                    self.layers[index] = data["name"]
                    self.layer_flags[index] = {k: v for k, v in data.items() if k != "name"}
                    out.append({"attributeId": {"guid": layer_guid(index)}})
            return ok({"addOnCommandResponse": {"attributeIds": out}})
        if name == "SetDetailsOfElements":
            out = []
            for position, row in enumerate(args["elementsWithDetails"]):
                guid = row["elementId"]["guid"]
                if position in self.layer_move_errors:
                    out.append(deepcopy(self.layer_move_errors[position]))
                elif guid not in self.elements:
                    out.append(deepcopy(LAYERS_FIXTURE["set_details_missing"]))
                else:
                    if not self.layer_move_ignored:
                        current = self.details.setdefault(guid, {"type": self.elements[guid]})
                        current.update(row["details"])
                    out.append(deepcopy(LAYERS_FIXTURE["set_details_ok"]))
            return ok({"addOnCommandResponse": {"executionResults": out}})
        if name == "GetAttributesByType" and args["attributeType"] == "LayerCombination":
            rows = [
                {"attributeId": {"guid": combination_guid(i)}, "index": i, "name": c["name"]}
                for i, c in self.layer_combinations.items()
            ]
            return ok({"addOnCommandResponse": {"attributes": rows}})
        if name == "GetLayerCombinations":
            out = []
            for row in args["attributes"]:
                guid = row["attributeId"]["guid"]
                index = next(
                    (i for i in self.layer_combinations if combination_guid(i) == guid), None
                )
                if index is None:
                    out.append(
                        {
                            "error": {
                                "code": -2130313112,
                                "message": "Failed to retrieve layer combination attribute.",
                            }
                        }
                    )
                    continue
                if index in self.layer_combination_read_errors:
                    out.append(deepcopy(self.layer_combination_read_errors[index]))
                    continue
                combination = self.layer_combinations[index]
                layers = [
                    {
                        "attributeId": {"guid": layer_guid(layer)},
                        "isHidden": False,
                        "isLocked": False,
                        "isWireframe": False,
                        "intersectionGroupNr": 1,
                        **combination["layers"].get(layer, {}),
                    }
                    for layer in self.layers
                ]
                out.append(
                    {
                        "layerCombination": {
                            "attributeId": {"guid": guid},
                            "attributeIndex": index,
                            "name": combination["name"],
                            "layers": layers,
                        }
                    }
                )
            return ok({"addOnCommandResponse": {"layerCombinations": out}})
        if name == "GetAttributesByType" and args["attributeType"] == "Surface":
            rows = [
                {"attributeId": {"guid": surface_guid(i)}, "index": i, "name": n}
                for i, n in self.surfaces.items()
            ]
            return ok({"addOnCommandResponse": {"attributes": rows}})
        if name == "GetAttributesByType" and args["attributeType"] == "Fill":
            return ok({"addOnCommandResponse": {"attributes": deepcopy(DRAFTING_FIXTURE["fills"])}})
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
                            and not self._on_locked_layer(e["elementId"]["guid"])
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
        if name == "CreateRoofs":
            out = []
            for index, roof in enumerate(args["roofsData"]):
                if index in self.create_errors:
                    out.append(deepcopy(self.create_errors[index]))
                    continue
                guid = str(uuid4()).upper()
                self.elements[guid] = "Roof"
                row = deepcopy(ROOFS_TEXTS_FIXTURE["roof_details"])
                story = next(s for s in self.stories if s["index"] == roof["floorIndex"])
                row["floorIndex"] = roof["floorIndex"]
                details = row["details"]
                points = deepcopy(roof["polygonCoordinates"])
                structure = roof.get("structureType", self.roof_default_structure)
                details.update(
                    structureType=structure,
                    thickness=roof["thickness"] if structure == "Basic" else 0.30,
                    level=roof["level"] - story["level"],
                    zCoordinate=roof["level"],
                    polygonOutline=points + [deepcopy(points[0])],
                )
                if "pivotLine" in roof:
                    for key in ("eavesOverhang", "levels", "pivotPolygonOutline"):
                        details.pop(key)
                    details.update(
                        roofClass="SinglePlane",
                        angle=roof["angle"],
                        pivotLine={
                            "begin": deepcopy(roof["pivotLine"]["begCoordinate"]),
                            "end": deepcopy(roof["pivotLine"]["endCoordinate"]),
                        },
                    )
                else:
                    # Multi-plane: the outline is the pivot polygon; the contour grows.
                    details["pivotPolygonOutline"] = deepcopy(points)
                    grow = roof.get("eavesOverhang", details["eavesOverhang"])
                    details["eavesOverhang"] = grow
                    details["polygonOutline"] = [
                        {"x": p["x"] + grow, "y": p["y"] + grow} for p in points
                    ]
                    if "levels" in roof:
                        details["levels"] = [
                            {"height": v["levelHeight"], "angle": v["levelAngle"]}
                            for v in roof["levels"]
                        ]
                self.details[guid] = row
                out.append(self._id(guid))
            return ok({"addOnCommandResponse": {"elements": out}})
        if name == "CreateInteriorElevations":
            # Shapes from the Tapir 1.7.0 source (CreateInteriorElevationsCommand,
            # NavigatorCommands InteriorElevationItem); not captured live. One Project Map
            # item per segment is an assumption to confirm live.
            out = []
            for index, data in enumerate(args["interiorElevationsData"]):
                assert set(data) <= {"nodeCoordinates", "depth", "name", "id", "floorIndex"}
                if index in self.create_errors:
                    out.append(deepcopy(self.create_errors[index]))
                    continue
                guid = str(uuid4()).upper()
                self.elements[guid] = "InteriorElevation"
                floor = data.get("floorIndex", 0)
                self.details[guid] = {
                    "type": "InteriorElevation",
                    "floorIndex": floor,
                    "layerIndex": 1,
                }
                for segment in range(len(data["nodeCoordinates"]) - 1):
                    self.navigator_trees["ProjectMap"].setdefault("children", []).append(
                        {
                            "navigatorItem": {
                                "navigatorItemId": {"guid": str(uuid4()).upper()},
                                "type": "InteriorElevationItem",
                                "name": self.section_stored_name or data.get("name", ""),
                                "prefix": "",
                                "uiId": f"{data.get('id', 'IE-01')}/{segment + 1}",
                                "customUiId": "id" in data,
                                "customName": True,
                            }
                        }
                    )
                out.append(self._id(guid))
            return ok({"addOnCommandResponse": {"elements": out}})
        if name == "CreateSections":
            # Shapes from the Tapir 1.7.0 source (CreateSectionsCommand, GetDetailsOfElements
            # header fields, NavigatorCommands SectionItem); not captured live.
            out = []
            for index, data in enumerate(args["sectionsData"]):
                if index in self.create_errors:
                    out.append(deepcopy(self.create_errors[index]))
                    continue
                guid = str(uuid4()).upper()
                self.elements[guid] = "CutPlane"
                floor = data.get("floorIndex", 0) + (1 if self.section_wrong_floor else 0)
                self.details[guid] = {"type": "CutPlane", "floorIndex": floor, "layerIndex": 1}
                nav = str(uuid4()).upper()
                count = sum(n.get("type") == "SectionItem" for n in self._nav_items("ProjectMap"))
                self.navigator_trees["ProjectMap"].setdefault("children", []).append(
                    {
                        "navigatorItem": {
                            "navigatorItemId": {"guid": nav},
                            "type": "SectionItem",
                            "name": self.section_stored_name or data.get("name", ""),
                            "prefix": "",
                            "uiId": f"S-{count + 1:02d}",
                            "customUiId": False,
                            "customName": True,
                        }
                    }
                )
                out.append(self._id(guid))
            return ok({"addOnCommandResponse": {"elements": out}})
        if name in DRAFTING_COMMANDS:
            kind, key = DRAFTING_COMMANDS[name]
            out = []
            for index, data in enumerate(args[key]):
                if index in self.create_errors:
                    out.append(deepcopy(self.create_errors[index]))
                    continue
                guid = str(uuid4()).upper()
                self.elements[guid] = kind
                details = deepcopy(DRAFTING_FIXTURE["details"][kind])
                for field_name in (
                    "begCoordinate",
                    "endCoordinate",
                    "origin",
                    "radius",
                    "begAngle",
                    "endAngle",
                    "linePenIndex",
                    "fillPenIndex",
                    "contourPenIndex",
                    "fillId",
                ):
                    if field_name in data and field_name in details:
                        details[field_name] = deepcopy(data[field_name])
                self.details[guid] = {
                    "type": kind,
                    "floorIndex": data.get("floorInd", 0),
                    "layerIndex": data.get("layerIndex", 1),
                    "details": details,
                }
                if "coordinates" in data:
                    shift = self.drafting_coordinate_shift
                    details["coordinates"] = [
                        {"x": q["x"] + shift, "y": q["y"]} for q in data["coordinates"]
                    ]
                    if kind == "Hatch":
                        # Not captured live: the check accepts a closing repeat or none.
                        details["coordinates"].append(dict(details["coordinates"][0]))
                if kind == "Circle":
                    # Archicad 30 reads a circle back as a full Arc (live, 14/10/2026).
                    self.elements[guid] = self.details[guid]["type"] = "Arc"
                    details |= {"begAngle": 0.0, "endAngle": 0.0}
                out.append(self._id(guid))
            return ok({"addOnCommandResponse": {"elements": out}})
        if name == "CreateLabels":
            out = []
            for index, label in enumerate(args["labelsData"]):
                if index in self.create_errors:
                    out.append(deepcopy(self.create_errors[index]))
                    continue
                parent = label.get("parentElementId", {}).get("guid")
                if parent is not None and parent not in self.elements:
                    error = {"code": -2130313112, "message": "Invalid parent element GUID"}
                    out.append({"error": error})
                    continue
                if parent is None and "begCoordinate" not in label:
                    out.append(deepcopy(LABELS_FIXTURE["missing_coordinate"]))
                    continue
                guid = str(uuid4()).upper()
                self.elements[guid] = "Label"
                row = deepcopy(LABELS_FIXTURE["label_details"])
                details = row["details"]
                if parent is not None:
                    row["floorIndex"] = self.details.get(parent, {}).get("floorIndex", 0)
                    details["ownerElementId"] = {"guid": parent.lower()}
                    details["ownerElementType"] = self.elements[parent]
                else:
                    row["floorIndex"] = label.get("floorInd", 0)
                if "begCoordinate" in label:
                    details["begCoordinate"] = dict(label["begCoordinate"])
                details["labelClass"] = label.get("labelClass", "Text")
                details["text"] = (
                    self.text_stored_as if self.text_stored_as is not None else label["text"]
                )
                details["style"].update(label.get("style", {}))
                self.details[guid] = row
                out.append(self._id(guid))
            return ok({"addOnCommandResponse": {"elements": out}})
        if name == "CreateTexts":
            out = []
            for index, text in enumerate(args["textsData"]):
                if index in self.create_errors:
                    out.append(deepcopy(self.create_errors[index]))
                    continue
                guid = str(uuid4()).upper()
                self.elements[guid] = "Text"
                row = deepcopy(ROOFS_TEXTS_FIXTURE["text_details"])
                row["floorIndex"] = text["floorIndex"]
                details = row["details"]
                details["position"] = {k: text["coordinate"][k] for k in ("x", "y")}
                details["text"] = (
                    self.text_stored_as if self.text_stored_as is not None else text["text"]
                )
                for key in ("angle", "height", "justification"):
                    if key in text:
                        details[key] = text[key]
                details["paragraphCount"] = details["text"].count("\n") + 1
                self.details[guid] = row
                out.append(self._id(guid))
            return ok({"addOnCommandResponse": {"elements": out}})
        if name == "CreateWallThicknessDimensions":
            # Shapes from Tapir 1.7.0 source (ExtendedElementCommands.cpp); not live.
            out = []
            for index, data in enumerate(args["dimensionsData"]):
                wall = data["wallId"]["guid"]
                if index in self.create_errors:
                    out.append(deepcopy(self.create_errors[index]))
                    continue
                if self.elements.get(wall) != "Wall":
                    out.append(
                        {
                            "error": {
                                "code": -2130313100,
                                "message": "Failed to load wall for associative dimension.",
                            }
                        }
                    )
                    continue
                guid = str(uuid4()).upper()
                self.elements[guid] = "Dimension"
                floor = self.details.get(wall, {}).get("floorIndex", 0)
                self.details[guid] = {
                    "type": "Dimension",
                    "floorIndex": floor + self.dimension_floor_shift,
                    "layerIndex": 1,
                    "details": {},
                }
                out.append(self._id(guid))
            return ok({"addOnCommandResponse": {"elements": out}})
        if name == "CreateMorphs":
            # Shapes from Tapir 1.7.0 source (CreateMorphs, AddMorphBodyFromMemo); not live.
            out = []
            for index, morph in enumerate(args["morphsData"]):
                if index in self.create_errors:
                    out.append(deepcopy(self.create_errors[index]))
                    continue
                guid = str(uuid4()).upper()
                self.elements[guid] = "Morph"
                base, size = morph["basePoint"], morph["size"]
                self.details[guid] = {
                    "type": "Morph",
                    "floorIndex": morph["floorIndex"],
                    "layerIndex": 1,
                    "details": {
                        "origin": deepcopy(base),
                        "xAxis": {"x": 1.0, "y": 0.0, "z": 0.0},
                        "yAxis": {"x": 0.0, "y": 1.0, "z": 0.0},
                        "zAxis": {"x": 0.0, "y": 0.0, "z": 1.0},
                        "castShadow": True,
                        "receiveShadow": True,
                        "isAutoOnStoryVisibility": True,
                    },
                }
                shift = self.morph_box_shift
                self.bounding_boxes_3d[guid] = {
                    "boundingBox3D": {
                        "xMin": base["x"] + shift,
                        "yMin": base["y"],
                        "zMin": base["z"],
                        "xMax": base["x"] + size["x"] + shift,
                        "yMax": base["y"] + size["y"],
                        "zMax": base["z"] + size["z"],
                    }
                }
                out.append(self._id(guid))
            return ok({"addOnCommandResponse": {"elements": out}})
        if name == "CreateMeshes":
            out = []
            for index, mesh in enumerate(args["meshesData"]):
                if index in self.create_errors:
                    out.append(deepcopy(self.create_errors[index]))
                    continue
                guid = str(uuid4()).upper()
                self.elements[guid] = "Mesh"
                row = deepcopy(MESHES_FIXTURE["mesh_details"])
                row["floorIndex"] = mesh["floorIndex"]
                points = deepcopy(mesh["polygonCoordinates"])
                row["details"].update(
                    {
                        k: deepcopy(mesh[k])
                        for k in ("level", "skirtType", "skirtLevel", "ridges", "showLines")
                    }
                )
                row["details"]["level"] += self.mesh_base_shift
                row["details"].update(
                    polygonCoordinates=points + [deepcopy(points[0])],
                    polygonArcs=deepcopy(mesh.get("polygonArcs", [])),
                    holes=deepcopy(mesh.get("holes", [])),
                )
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
                rows.append(
                    deepcopy(
                        MESHES_FIXTURE["modify_error"]
                        if name == "ModifyMeshes"
                        else MODIFY_LABELS_FIXTURE["failure"]
                        if name == "ModifyLabels"
                        else MODIFY_ELEMENTS_FIXTURE["failures"][name]
                    )
                )
                continue
            if not self.modify_ignored:
                row = self.details[guid]
                details = row["details"]
                story = next(s for s in self.stories if s["index"] == row["floorIndex"])
                changes = {k: deepcopy(v) for k, v in entry.items() if k != "elementId"}
                if name == "ModifyMeshes":
                    changes = changes["meshData"]
                if name == "ModifyRoofs":
                    if details.get("roofClass") != "MultiPlane":
                        rows.append(
                            deepcopy(MODIFY_ELEMENTS_FIXTURE["failures"]["ModifyRoofsSingle"])
                        )
                        continue
                    if "level" in changes:  # absolute, Tapir picks the story
                        z = changes.pop("level")
                        row["floorIndex"], details["level"] = self._floor(z)
                        details["zCoordinate"] = z
                    if "levels" in changes:
                        details["levels"] = [
                            {"height": v["levelHeight"], "angle": v["levelAngle"]}
                            for v in changes.pop("levels")
                        ]
                if name == "ModifyTexts":
                    if "coordinate" in changes:
                        coordinate = changes.pop("coordinate")
                        details["position"] = {k: coordinate[k] for k in ("x", "y")}
                        row["floorIndex"] = changes.pop(
                            "floorIndex", self._floor(coordinate["z"])[0]
                        )
                    details.update(changes.pop("style", {}))
                    if "text" in changes:
                        changes["text"] = changes["text"].replace("\r\n", "\n")
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
                if name == "ModifyObjects" and "dimensions" in changes:
                    # Live AC30 build 3001 BRA (14/10/2026): x and y change, the height
                    # (ZZYZX) does not, and dimensions.z always reads back as 0.
                    changes["dimensions"] = {**changes["dimensions"], "z": 0}
                if name == "ModifyLabels":
                    if details.get("labelClass") != "Text":
                        rows.append(deepcopy(MODIFY_LABELS_FIXTURE["failure"]))
                        continue
                    details.setdefault("style", {}).update(changes.pop("style", {}))
                    if "text" in changes:
                        changes["text"] = changes["text"].replace("\r\n", "\n").replace("\r", "\n")
                details.update(changes)
            rows.append(deepcopy(MODIFY_ELEMENTS_FIXTURE["success"]))
        return ok({"addOnCommandResponse": {"executionResults": rows}})

    def _rename(self, name: str, args: dict) -> dict:
        failed = {"success": False, "error": {"code": -2130313112, "message": "Failed to rename"}}
        missing_layers = name == "CreateLayerCombinations" and any(
            "layers" not in d for d in args["layerCombinationDataArray"]
        )
        if self.rename_call_refused or missing_layers:
            # Live AC30 build 3001 BRA, Tapir 1.7.0 (14/10/2026): a combination without
            # "layers" is refused by the schema check; the error code here is not captured.
            return fail(
                -2130313112,
                "Validation failed on schema rule 'required' at path "
                "'#/layerCombinationDataArray/0'",
            )
        if name == "RenameNavigatorItem":
            guid = args["navigatorItemId"]["guid"]
            nodes = [n for tree in self.navigator_trees.values() for n in self._nav_items_of(tree)]
            node = next((n for n in nodes if n["navigatorItemId"]["guid"] == guid), None)
            if 0 in self.rename_errors or node is None:
                self.rename_errors.pop(0, None)
                return ok({"addOnCommandResponse": deepcopy(failed)})
            if not self.rename_ignored:
                node["name"], node["customName"] = args["newName"], True
            return ok({"addOnCommandResponse": {"success": True}})
        if name.startswith("Create"):
            key = {
                "CreateLayers": "layerDataArray",
                "CreateBuildingMaterials": "buildingMaterialDataArray",
                "CreateSurfaces": "surfaceDataArray",
                "CreateLayerCombinations": "layerCombinationDataArray",
            }[name]
            out = []
            for position, data in enumerate(args[key]):
                guid = data["attributeId"]["guid"]
                if name == "CreateBuildingMaterials":
                    store = {g: r for g, r in self.building_materials.items() if "error" not in r}
                    found = guid in store
                elif name == "CreateLayerCombinations":
                    assert data["layers"] == []  # never a layer table, only the name
                    table = self.layer_combinations
                    index = next((i for i in table if combination_guid(i) == guid), None)
                    found = index is not None
                else:
                    table = self.layers if name == "CreateLayers" else self.surfaces
                    make = layer_guid if name == "CreateLayers" else surface_guid
                    index = next((i for i in table if make(i) == guid), None)
                    found = index is not None
                if position in self.rename_errors or not found:
                    error = self.rename_errors.get(position)
                    out.append({"error": deepcopy(error or {"code": -1, "message": "Failed."})})
                    continue
                if not self.rename_ignored:
                    if name == "CreateBuildingMaterials":
                        self.building_materials[guid]["name"] = data["name"]
                    elif name == "CreateLayerCombinations":
                        table[index]["name"] = data["name"]
                        if self.combination_reset_on_rename:
                            table[index]["layers"] = {}
                    else:
                        table[index] = data["name"]
                out.append({"attributeId": {"guid": guid}})
            return ok({"addOnCommandResponse": {"attributeIds": out}})
        key = {
            "RenameFavorites": "renames",
            "UpdateClassificationSystems": "classificationSystems",
            "UpdateClassificationItems": "classificationItems",
            "UpdatePropertyGroups": "propertyGroups",
            "UpdatePropertyDefinitions": "propertyDefinitions",
        }[name]
        out = []
        for position, row in enumerate(args[key]):
            target = self._rename_target(name, row)
            if position in self.rename_errors or target is None:
                out.append(deepcopy(self.rename_errors.get(position, failed)))
                continue
            if not self.rename_ignored:
                if name == "RenameFavorites":
                    names = target
                    names[names.index(row["oldName"])] = row["newName"]
                elif name == "UpdatePropertyDefinitions":
                    target["propertyName"] = row["name"]
                else:
                    target.update({k: v for k, v in row.items() if k in ("id", "name")})
            out.append({"success": True})
        return ok({"addOnCommandResponse": {"executionResults": out}})

    def _rename_target(self, name: str, row: dict) -> Any:
        if name == "RenameFavorites":
            return next((n for n in self.favorites.values() if row["oldName"] in n), None)
        if name == "UpdatePropertyGroups":
            guid = row["propertyGroupId"]["guid"]
            groups = self.property_groups
            return next((g for g in groups if g["propertyGroupId"]["guid"] == guid), None)
        if name == "UpdatePropertyDefinitions":
            guid = row["propertyId"]["guid"]
            props = self.custom_properties
            return next((p for p in props if p["propertyId"]["guid"] == guid), None)
        if name == "UpdateClassificationSystems":
            guid = row["classificationSystemId"]["guid"]
            systems = self.classification_data["systems"]["classificationSystems"]
            return next((s for s in systems if s["classificationSystemId"]["guid"] == guid), None)
        guid = row["classificationItemId"]["guid"]
        stack = [
            entry["classificationItem"]
            for tree in self.classification_data["items"].values()
            for entry in tree["classificationItems"]
        ]
        while stack:
            item = stack.pop()
            if item["classificationItemId"]["guid"] == guid:
                return item
            stack += [c["classificationItem"] for c in item.get("children", [])]
        return None

    def _nav_items_of(self, tree: dict) -> list[dict]:
        out, stack = [], [tree]
        while stack:
            node = stack.pop()
            out.append(node)
            stack += [c["navigatorItem"] for c in node.get("children", [])]
        return out

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
        if instance.lose_mesh_response and command == "CreateMeshes":
            raise httpx.ReadTimeout(
                "Injected lost mesh response after model change", request=request
            )
        if instance.lose_section_response and command == "CreateInteriorElevations":
            raise httpx.ReadTimeout("Injected lost interior elevation response", request=request)
        if instance.lose_section_response and command == "CreateSections":
            raise httpx.ReadTimeout("Injected lost section response", request=request)
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
        if instance.lose_roof_response and command == "CreateRoofs":
            raise httpx.ReadTimeout("Injected lost roof response", request=request)
        if instance.lose_text_response and command == "CreateTexts":
            raise httpx.ReadTimeout("Injected lost text response", request=request)
        if instance.lose_rename_response and (
            command in RENAME_COMMANDS
            or body.get("command") == "API.RenameAttributeFolders"
            or (
                command in RENAME_OVERWRITES
                and body["parameters"].get("addOnCommandParameters", {}).get("overwriteExisting")
            )
        ):
            raise httpx.ReadTimeout("Injected lost rename response", request=request)
        if instance.lose_drafting_response and command in DRAFTING_COMMANDS:
            raise httpx.ReadTimeout("Injected lost drafting response", request=request)
        if instance.lose_layer_response and command in ("CreateLayers", "SetDetailsOfElements"):
            raise httpx.ReadTimeout("Injected lost layer response", request=request)
        if instance.lose_project_info_response and command == "SetProjectInfoField":
            raise httpx.ReadTimeout("Injected lost project info response", request=request)
        if instance.lose_keynote_response and str(command).startswith("CreateKeynote"):
            raise httpx.ReadTimeout("Injected lost keynote response", request=request)
        if instance.lose_attribute_property_response and command == "SetPropertyValuesOfAttributes":
            raise httpx.ReadTimeout("Injected lost attribute property response", request=request)
        if instance.lose_favorite_create_response and command == "CreateFavoritesFromElements":
            raise httpx.ReadTimeout("Injected lost favorite response", request=request)
        if instance.lose_favorite_response and command == "ApplyFavoritesToElements":
            raise httpx.ReadTimeout("Injected lost favorite response", request=request)
        if instance.lose_property_definition_response and command in (
            "CreatePropertyGroups",
            "CreatePropertyDefinitions",
        ):
            raise httpx.ReadTimeout("Injected lost property definition response", request=request)
        if instance.lose_document_response and command in (
            "CreateWorksheets",
            "CreateDetails",
            "CreateLayout",
        ):
            raise httpx.ReadTimeout("Injected lost document response", request=request)
        if instance.lose_lock_response and command in ("LockElements", "UnlockElements"):
            raise httpx.ReadTimeout("Injected lost lock response", request=request)
        if instance.lose_zone_update_response and command == "UpdateZones":
            raise httpx.ReadTimeout("Injected lost zone update response", request=request)
        if instance.lose_group_response and command == "CreateGroups":
            raise httpx.ReadTimeout("Injected lost group response", request=request)
        if instance.lose_label_response and command == "CreateLabels":
            raise httpx.ReadTimeout("Injected lost label response", request=request)
        if instance.lose_classification_response and (
            body.get("command") == "API.SetClassificationsOfElements"
        ):
            raise httpx.ReadTimeout("Injected lost classification response", request=request)
        if command in ("CreateIssue", "AttachElementsToIssue"):
            issue_write_count = sum(
                c in ("CreateIssue", "AttachElementsToIssue") for c in instance.tapir_calls
            )
            if instance.lose_issue_response_at == issue_write_count:
                raise httpx.ReadTimeout(
                    "Injected lost issue response after change", request=request
                )
        if instance.lose_view_settings_response and command == "SetViewSettings":
            raise httpx.ReadTimeout(
                "Injected lost view settings response after change", request=request
            )
        if instance.lose_layer_settings_response and command == "CreateLayers":
            raise httpx.ReadTimeout(
                "Injected lost layer-settings response after change", request=request
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


# Source-derived Tapir 1.7.0 ModifyLabels response; not captured live.
MODIFY_LABELS_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "tapir170_modify_labels_documented.json").read_text(
        encoding="utf-8"
    )
)


# Source-derived command schemas and synthetic values; NOT a live capture.
ISSUES_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "tapir170_issues_documented.json").read_text(
        encoding="utf-8"
    )
)


# NavigatorCommands.cpp tag 1.7.0 shapes; synthetic values, NOT captured live.
NAVIGATOR_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "tapir170_navigator_documented.json").read_text(
        encoding="utf-8"
    )
)


# Tapir 1.7.0 source-derived Mesh shapes; synthetic values, NOT a live capture.
MESHES_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "tapir170_meshes_documented.json").read_text(
        encoding="utf-8"
    )
)


# Source-derived Tapir 1.7.0 ViewSettings schemas; synthetic values, NOT live.
VIEW_SETTINGS_FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "tapir170_view_settings_documented.json").read_text(
        encoding="utf-8"
    )
)
