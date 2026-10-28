"""P-005: target selection against MockTransport only; never a real Archicad."""

import inspect
from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import AmbiguousTarget, ArchicadClient, resolve_port
from archicad_mcp_aberto.server import create_server
from archicad_mcp_aberto.tools import (
    attribute_properties,
    attributes,
    attributes_details,
    camera_paths,
    classification_systems,
    classifications,
    collisions,
    composites,
    design_option_create,
    design_options,
    documents,
    drafting,
    drawings,
    edit,
    element_structure,
    favorites,
    gateway,
    grids,
    hotlinks,
    ifc,
    interior_elevations,
    issues,
    keynotes,
    labels,
    layer_settings,
    layers,
    layout_book,
    locks,
    mep,
    meshes,
    model_tasks,
    modify,
    morphs,
    navigator,
    navigator_moves,
    object_replacement,
    openings,
    preview_images,
    profiles,
    project_info,
    project_location,
    project_map_names,
    project_resources,
    project_save,
    property_definitions,
    read,
    renames,
    revisions,
    roofs,
    room_views,
    scenes,
    sections,
    selection,
    solids,
    stairs,
    stories,
    surfaces,
    texts,
    views,
    voids,
    wall_dimensions,
    write,
    zone_categories,
    zones,
    zones_read,
)
from tests.unit.fake_archicad import (
    BUILDING_MATERIALS_FIXTURE,
    CREATE_WALLS_FIXTURE,
    FakeArchicad,
    fake_transport,
)
from tests.unit.test_modify_elements import ROWS as MODIFY_ROWS

pytestmark = pytest.mark.anyio
GUID = "11111111-1111-1111-1111-111111111111"
PROP = "22222222-2222-2222-2222-222222222222"
# modify_* tool -> element type it edits
MODIFY_TYPES = {
    "modify_slabs": "Slab",
    "modify_columns": "Column",
    "modify_beams": "Beam",
    "modify_windows": "Window",
    "modify_doors": "Door",
    "modify_objects": "Object",
    "modify_lamps": "Lamp",
    "modify_roofs": "Roof",
    "modify_texts": "Text",
    "modify_labels": "Label",
    "modify_meshes": "Mesh",
    "modify_morphs": "Morph",
}
SCENE = {"name": "Sala - 1P 01", "camera": {"x": 0, "y": 0, "z": 1.3}, "target": {"x": 5, "y": 0}}
INPUTS = {
    "list_camera_paths": {},
    "create_camera_paths_from_views": {},
    "begin_model_task": {},
    "finish_model_task": {"task_token": "missing"},
    "save_project_as": {"destination_path": "example.pln"},
    "save_next_project_revision": {},
    "inspect_project_save": {"destination_path": "example.pln"},
    "inspect_object_replacements": {"guids": [GUID], "target_unid": "EXACT-UNID"},
    "replace_object_libraries": {
        "replacements": [
            {
                "guid": GUID,
                "target_unid": "EXACT-UNID",
                "source_mount": {"x": 0.1, "y": 0.0, "z": 0.0},
                "target_mount": {"x": 0.2, "y": 0.0, "z": 0.0},
            }
        ]
    },
    "read_scene_model": {},
    "shoot_3d_scenes": {"scenes": [SCENE]},
    "save_3d_scenes": {"scenes": [SCENE], "folder_path": ["AMBIENTES"]},
    "save_room_plan_views": {"folder_path": ["AMPLIACOES"]},
    "list_project_map_cameras": {},
    "list_hotlinks": {},
    "get_attribute_details": {"kind": "composites", "guids": []},
    "get_ifc_of_elements": {"element_guids": [GUID]},
    "find_elements_by_ifc_ids": {"ifc_ids": ["2O2Fr$t4X7Zf8NOew3FNvQ"]},
    "get_project_location": {},
    "get_layout_settings": {"layout_database_guids": [GUID]},
    "get_dimension_data": {"element_guids": [GUID]},
    "get_model_view_options": {},
    "list_libraries": {},
    "get_element_preview": {"element_guids": [GUID]},
    "get_zone_image": {"zone_guids": [GUID]},
    "get_favorite_preview": {"favorite_names": ["Wall"]},
    "get_zone_boundaries": {"zone_guids": [GUID]},
    "get_zone_relations": {"zone_guids": [GUID]},
    "create_layer_combinations": {
        "combinations": [{"name": "New", "layers": [{"layer": "Walls"}]}]
    },
    "list_mep_systems": {},
    "get_mep_elements": {},
    "get_mep_preference_tables": {"domain": "Piping"},
    "find_collisions": {"group1_guids": [GUID], "group2_guids": [PROP]},
    "list_document_revisions": {},
    "list_revision_issues": {},
    "get_revision_changes": {},
    "get_subelements": {"element_guids": [GUID]},
    "get_element_trims": {"element_guids": [GUID]},
    "get_solid_operation_links": {"element_guids": [GUID]},
    "get_section_elements": {},
    "list_design_options": {},
    "get_elements_of_design_options": {
        "design_option_guids": ["20000000-0000-4000-8000-000000000001"]
    },
    "get_design_options_for_elements": {"element_guids": [GUID]},
    "list_layer_combinations": {},
    "set_layer_settings": {"changes": [{"layer": "Editable", "locked": False}]},
    "get_view_settings": {"view_guids": ["77777777-7777-4777-8777-000000000003"]},
    "set_view_settings": {
        "changes": [{"guid": "77777777-7777-4777-8777-000000000003", "drawing_scale": 100}]
    },
    "create_meshes": {
        "meshes": [
            {
                "outline": [
                    {"x": 0, "y": 0, "z": 0},
                    {"x": 4, "y": 0, "z": 1},
                    {"x": 0, "y": 3, "z": 0},
                ],
                "floor_index": 0,
                "level": 0,
            }
        ]
    },
    "modify_meshes": {"meshes": [{"guid": GUID, "level": 0.5}]},
    "get_navigator_tree": {},
    "list_issues": {},
    "create_issues": {"issues": [{"name": "Review"}]},
    "attach_elements_to_issue": {
        "issue_guid": "99999999-9999-4999-8999-999999999999",
        "element_guids": [GUID],
    },
    "modify_labels": {"labels": [{"guid": GUID, "text": "Wall finish"}]},
    "run_read_command": {"command": "Tapir.GetStories"},
    "create_windows": {"windows": [{"wall_guid": GUID, "center_offset": 2.0}]},
    "create_doors": {"doors": [{"wall_guid": GUID, "center_offset": 2.0}]},
    "modify_walls": {"walls": [{"guid": GUID, "height": 4.0}]},
    "modify_slabs": {"slabs": [{"guid": GUID, "thickness": 0.2}]},
    "modify_roofs": {"roofs": [{"guid": GUID, "thickness": 0.2}]},
    "modify_texts": {"texts": [{"guid": GUID, "text": "Sala"}]},
    "create_roofs": {
        "roofs": [
            {
                "outline": [{"x": 0, "y": 0}, {"x": 4, "y": 0}, {"x": 0, "y": 3}],
                "floor_index": 0,
                "level": 3.0,
                "thickness": 0.2,
            }
        ]
    },
    "create_texts": {"texts": [{"text": "Sala", "position": {"x": 1, "y": 1}, "floor_index": 0}]},
    "create_labels": {"labels": [{"text": "Parede", "element_guid": GUID}]},
    "modify_morphs": {"morphs": [{"guid": GUID, "castShadow": False}]},
    "create_keynote_labels": {
        "labels": [{"keynote_item_guid": GUID, "position": {"x": 0, "y": 0}}]
    },
    "list_classifications": {},
    "list_layers": {},
    "get_project_info_fields": {},
    "set_project_info_fields": {"changes": [{"field": "PROJECTNAME", "value": "Casa"}]},
    "list_favorites": {"element_type": "Wall"},
    "apply_favorites": {"changes": [{"element_guid": GUID, "favorite": "Parede padrão"}]},
    "select_elements": {"element_guids": [GUID]},
    "highlight_elements": {"element_guids": [GUID]},
    "get_element_groups": {"element_guids": [GUID]},
    "create_groups": {"groups": [{"element_guids": [GUID, PROP]}]},
    "create_layers": {"layers": [{"name": "Cotas"}]},
    "create_zone_categories": {"categories": [{"name": "Varanda", "code": "VAR"}]},
    "create_design_options": {"sets": ["Cobertura"]},
    "place_hotlinks": {
        "placements": [
            {"source_path": "C:/m/banho.mod", "origin": {"x": 0, "y": 0}, "floor_index": 0}
        ]
    },
    "create_layout_subsets": {"subsets": [{"name": "Executivo"}]},
    "create_solid_operations": {"links": [{"target_guid": GUID, "operator_guid": PROP}]},
    "trim_to_roof": {"element_guids": [GUID], "roof_guid": PROP},
    "remove_solid_operations": {"links": [{"target_guid": GUID, "operator_guid": PROP}]},
    "remove_trims": {"element_guids": [GUID], "roof_guid": PROP},
    "move_to_design_options": {"moves": [{"element_guid": GUID, "option": "F-02"}]},
    "add_stories": {"stories": [{"name": "Cobertura", "level": 6.0}]},
    "update_drawings": {"layouts": ["Planta baixa"]},
    "move_navigator_items": {
        "map": "view_map",
        "moves": [{"item": "Door schedule", "folder": "Architecture"}],
    },
    "list_grid_elements": {},
    "create_grid_elements": {
        "grids": [{"start": {"x": 0, "y": 0}, "end": {"x": 0, "y": 9}, "floor_index": 0}]
    },
    "create_surfaces": {"surfaces": [{"name": "Pintura Azul", "based_on": "Pintura Branca"}]},
    "create_drawings": {
        "drawings": [
            {"view": "Ground floor", "layout": "Planta baixa", "position": {"x": 0.2, "y": 0.15}}
        ]
    },
    "create_composites": {
        "composites": [
            {
                "name": "Parede 15",
                "use_with": ["Wall"],
                "skins": [{"building_material": "Insulation", "thickness": 0.15}],
            }
        ]
    },
    "lock_elements": {"element_guids": [GUID]},
    "unlock_elements": {"element_guids": [GUID]},
    "update_zones": {},
    "list_property_groups": {},
    "create_worksheets": {"worksheets": [{"name": "Rascunho", "reference_id": "W2"}]},
    "create_details": {"details": [{"name": "Detalhe da escada", "reference_id": "D1"}]},
    "create_layouts": {"layouts": [{"name": "Cortes", "master": "A3 Paisagem"}]},
    "create_profiles": {
        "profiles": [{"name": "New profile", "source_profile": "Rectangular 20x40"}]
    },
    "rename_items": {"kind": "layers", "find": "Walls", "replace": "Paredes"},
    "create_property_groups": {"groups": [{"name": "Obra"}]},
    "create_properties": {"properties": [{"name": "Lote", "group": "Projeto", "type": "string"}]},
    "set_element_layers": {"changes": [{"element_guid": GUID, "layer": "Walls"}]},
    "create_lines": {
        "lines": [{"start": {"x": 0, "y": 0}, "end": {"x": 1, "y": 0}, "floor_index": 0}]
    },
    "create_polylines": {
        "polylines": [{"points": [{"x": 0, "y": 0}, {"x": 1, "y": 0}], "floor_index": 0}]
    },
    "create_splines": {
        "splines": [
            {"points": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}], "floor_index": 0}
        ]
    },
    "create_hotspots": {"hotspots": [{"position": {"x": 0, "y": 0}, "floor_index": 0}]},
    "create_arcs": {
        "arcs": [
            {
                "center": {"x": 0, "y": 0},
                "radius": 1,
                "start_angle": 0,
                "end_angle": 1.0,
                "floor_index": 0,
            }
        ]
    },
    "create_circles": {"circles": [{"center": {"x": 0, "y": 0}, "radius": 1, "floor_index": 0}]},
    "create_fills": {
        "fills": [
            {"outline": [{"x": 0, "y": 0}, {"x": 4, "y": 0}, {"x": 0, "y": 3}], "floor_index": 0}
        ]
    },
    "set_classifications": {
        "changes": [{"element_guid": GUID, "system": "Uniclass", "item": None}]
    },
    "modify_columns": {"columns": [{"guid": GUID, "height": 3.0}]},
    "modify_beams": {"beams": [{"guid": GUID, "level": 3.0}]},
    "modify_windows": {"windows": [{"guid": GUID, "width": 1.0}]},
    "modify_doors": {"doors": [{"guid": GUID, "width": 1.0}]},
    "modify_objects": {"objects": [{"guid": GUID, "origin": {"x": 0, "y": 0}}]},
    "modify_lamps": {"lamps": [{"guid": GUID, "lightIsOn": False}]},
    "get_gdl_parameters": {"element_guids": [GUID]},
    "set_gdl_parameters": {"changes": [{"element_guid": GUID, "name": "A", "value": 2.0}]},
    "rotate_elements": {
        "rotations": [{"guid": GUID, "center": {"x": 0, "y": 0}, "angle": 1.5707963267948966}]
    },
    "list_library_parts": {},
    "create_zones": {
        "zones": [
            {
                "outline": [{"x": 0, "y": 0}, {"x": 4, "y": 0}, {"x": 0, "y": 3}],
                "name": "Room",
                "number": "01",
                "floor_index": 0,
            }
        ]
    },
    "create_beams": {
        "beams": [
            {
                "start": {"x": 0, "y": 0},
                "end": {"x": 4, "y": 0},
                "floor_index": 0,
                "level": 3,
                "width": 0.2,
                "height": 0.4,
            }
        ]
    },
    "delete_elements": {"element_guids": [GUID]},
    "find_elements": {},
    "set_property_values": {
        "changes": [{"element_guid": GUID, "property_guid": PROP, "value": "novo"}]
    },
    "move_elements": {"moves": [{"guid": GUID, "vector": {"x": 1, "y": 0}}]},
    "create_objects": {
        "objects": [
            {
                "library_part_name": "Mesa Retangular 30",
                "origin": {"x": 1, "y": 2},
                "floor_index": 0,
                "base_level": 0,
            }
        ]
    },
    "create_lamps": {
        "lamps": [
            {
                "library_part_name": "Pendente 01",
                "origin": {"x": 1, "y": 2},
                "floor_index": 0,
                "base_level": 2.5,
            }
        ]
    },
    "get_bounding_boxes": {"element_ids": [GUID]},
    "list_keynotes": {},
    "create_keynote_folders": {"folders": [{"key": "01", "title": "Paredes"}]},
    "create_keynote_items": {"items": [{"key": "01.01", "title": "Alvenaria"}]},
    "create_openings": {
        "openings": [
            {"owner_guid": GUID, "base_point": {"x": 1, "y": 0, "z": 0.5}, "width": 1, "height": 1}
        ]
    },
    "create_associative_dimensions": {
        "dimensions": [
            {
                "points": [
                    {"wall_guid": GUID, "end": "start"},
                    {"wall_guid": GUID, "end": "end"},
                ],
                "reference_point": {"x": 0, "y": 1},
            }
        ]
    },
    "create_wall_thickness_dimensions": {
        "dimensions": [
            {
                "wall_guid": GUID,
                "reference_point": {"x": 0, "y": 0},
                "direction": {"x": 0, "y": 1},
            }
        ]
    },
    "create_stairs": {
        "stairs": [
            {
                "start": {"x": 0, "y": 0},
                "end": {"x": 3, "y": 0},
                "floor_index": 0,
                "base_level": 0,
                "total_height": 2.8,
            }
        ]
    },
    "create_morphs": {
        "morphs": [
            {
                "base_point": {"x": 0, "y": 0, "z": 0},
                "size_x": 1,
                "size_y": 2,
                "size_z": 3,
                "floor_index": 0,
            }
        ]
    },
    "create_interior_elevations": {
        "interior_elevations": [
            {
                "nodes": [{"x": 0, "y": 0}, {"x": 4, "y": 0}, {"x": 4, "y": 3}],
                "closed": True,
                "floor_index": 0,
                "name": "Vista interna Sala",
            }
        ]
    },
    "set_attribute_property_values": {
        "changes": [{"attribute_guid": GUID, "property_guid": PROP, "value": "Fornecedor A"}]
    },
    "update_favorites_from_elements": {
        "favorites": [{"element_guid": GUID, "favorite": "Parede padrão"}]
    },
    "create_favorites_from_elements": {
        "favorites": [{"element_guid": GUID, "favorite": "Parede nova"}]
    },
    "create_sections": {
        "sections": [
            {
                "start": {"x": 0, "y": 0},
                "end": {"x": 4, "y": 0},
                "floor_index": 0,
                "name": "Corte A",
            }
        ]
    },
    "create_columns": {
        "columns": [
            {
                "origin": {"x": 0, "y": 0},
                "floor_index": 0,
                "height": 3,
                "base_level": 0,
                "width": 0.3,
                "depth": 0.5,
            }
        ]
    },
    "list_building_materials": {},
    "list_elements": {},
    "get_selection": {},
    "list_properties": {},
    "get_properties": {"element_guids": [GUID], "property_guids": [PROP]},
    "get_project_info": {},
    "get_stories": {},
    "get_element_details": {"element_guids": [GUID]},
    "create_walls": {
        "walls": [
            {
                "start": {"x": 0, "y": 0},
                "end": {"x": 4, "y": 0},
                "floor_index": 0,
                "height": 3,
                "thickness": 0.2,
            }
        ]
    },
    # This branch starts from main before PR #5; include slabs once that tool is merged.
    "create_slabs": {
        "slabs": [
            {
                "outline": [{"x": 0, "y": 0}, {"x": 4, "y": 0}, {"x": 0, "y": 3}],
                "floor_index": 0,
                "thickness": 0.2,
                "level": 0,
            }
        ]
    },
    "add_comment_to_issue": {
        "comments": [{"issue_guid": "99999999-9999-4999-8999-999999999999", "text": "Review"}]
    },
    "create_view_map_folders": {
        "folders": [{"parent_guid": "77777777-7777-4777-8777-000000000002", "name": "New"}]
    },
    "clone_to_view_map": {
        "views": [
            {
                "parent_guid": "77777777-7777-4777-8777-000000000002",
                "source_guid": "88888888-8888-4888-8888-000000000002",
            }
        ]
    },
    "create_classification_systems": {
        "systems": [{"name": "LAB", "version": "1", "items": [{"id": "01", "name": "A"}]}]
    },
    "create_classification_items": {
        "items": [
            {
                "system_guid": "1C4E9A10-3B7F-4D2A-9E61-0A5B7C3D2E11",
                "parent_guid": "A1000000-0000-4000-8000-000000000003",
                "id": "LAB-01",
                "name": "LAB item",
            }
        ]
    },
}
REMOVALS = ("remove_solid_operations", "remove_trims")
TARGETED = {
    name: function
    for module in (
        camera_paths,
        model_tasks,
        attribute_properties,
        attributes_details,
        attributes,
        classification_systems,
        classifications,
        collisions,
        collisions,
        design_options,
        documents,
        drafting,
        drawings,
        renames,
        edit,
        element_structure,
        element_structure,
        favorites,
        gateway,
        hotlinks,
        ifc,
        ifc,
        interior_elevations,
        issues,
        keynotes,
        labels,
        layer_settings,
        layers,
        layout_book,
        locks,
        mep,
        meshes,
        modify,
        morphs,
        navigator,
        grids,
        navigator_moves,
        openings,
        preview_images,
        object_replacement,
        project_info,
        project_save,
        project_location,
        project_location,
        project_resources,
        project_resources,
        profiles,
        property_definitions,
        read,
        revisions,
        revisions,
        roofs,
        project_map_names,
        room_views,
        scenes,
        sections,
        selection,
        solids,
        surfaces,
        stairs,
        stories,
        texts,
        views,
        voids,
        wall_dimensions,
        write,
        zones,
        zone_categories,
        composites,
        design_option_create,
        drawings,
        zones_read,
    )
    for name, function in inspect.getmembers(module, inspect.iscoroutinefunction)
    if function.__module__ == module.__name__
    and not name.startswith("_")
    and "port" in inspect.signature(function).parameters
}


def instances(second_state="ready"):
    first = FakeArchicad(
        19723,
        project_name="First",
        elements={GUID: "Wall"},
        selection=[GUID],
        properties={PROP: "Test property"},
    )
    second = FakeArchicad(
        19724,
        project_name="Second",
        elements={GUID: "Wall"},
        selection=[GUID],
        properties={PROP: "Test property"},
        busy=second_state == "busy",
        tapir_version=None if second_state == "no_tapir" else "1.7.0",
    )
    for instance in (first, second):
        row = {"keynoteItemId": {"guid": GUID}, "key": "K-LABEL", "title": "Piso"}
        instance.keynotes["itemsInRoot"].append(row)
    return first, second


def client(first, second, reversed_ports=False):
    ports = (19724, 19723) if reversed_ports else (19723, 19724)
    return ArchicadClient(ports=ports, transport=fake_transport(first, second))


async def test_all_registered_targeted_tools_have_cases():
    tools = await create_server().list_tools()
    registered = {tool.name for tool in tools if "port" in tool.inputSchema["properties"]}
    assert registered == set(TARGETED)
    assert registered <= INPUTS.keys()


@pytest.mark.parametrize("name", sorted(TARGETED))
@pytest.mark.parametrize("explicit_none", [False, True], ids=["omitted-port", "null-port"])
@pytest.mark.parametrize("second_state", ["ready", "busy", "no_tapir"])
async def test_every_targeted_tool_refuses_two_instances(
    name, explicit_none, second_state, tmp_path, monkeypatch
):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path / "receipts"))
    first, second = instances(second_state)
    arguments = deepcopy(INPUTS[name])
    if explicit_none:
        arguments["port"] = None
    async with client(first, second) as c:
        with pytest.raises(AmbiguousTarget, match="19723, 19724"):
            await TARGETED[name](c, **arguments)
    # Discovery probes both ports, but no model read/write may choose either instance.
    assert first.calls == second.calls == ["API.GetProductInfo"]
    assert first.tapir_calls == second.tapir_calls == []
    assert first.elements == second.elements == {GUID: "Wall"}
    assert not (tmp_path / "receipts").exists()


@pytest.mark.parametrize("name", sorted(TARGETED))
async def test_reversing_probe_order_does_not_select_first_instance(name):
    first, second = instances()
    async with client(first, second, reversed_ports=True) as c:
        with pytest.raises(AmbiguousTarget, match="19724, 19723"):
            await TARGETED[name](c, **deepcopy(INPUTS[name]))
    assert first.calls == second.calls == ["API.GetProductInfo"]


@pytest.mark.parametrize("name", sorted(TARGETED))
@pytest.mark.parametrize("port", [19723, 19724])
async def test_explicit_port_reaches_only_requested_instance(name, port):
    first, second = instances()
    if name in {"modify_walls", "create_windows", "create_doors", "create_associative_dimensions"}:
        for instance in (first, second):
            instance.details[GUID] = deepcopy(CREATE_WALLS_FIXTURE["wall_details"])
    if name in {"get_gdl_parameters", "set_gdl_parameters"}:
        for instance in (first, second):
            instance.elements[GUID] = "Object"
    if name in MODIFY_TYPES:
        for instance in (first, second):
            instance.elements[GUID] = MODIFY_TYPES[name]
            instance.details[GUID] = deepcopy(MODIFY_ROWS[MODIFY_TYPES[name]])
    if name == "set_layer_settings":
        for instance in (first, second):
            instance.layers[2] = "Editable"
    if name == "create_groups":
        for instance in (first, second):
            instance.elements[PROP] = "Wall"
    if name == "set_attribute_property_values":
        for instance in (first, second):
            instance.attribute_property_values[(GUID, PROP)] = "Fornecedor"
    if name in ("create_solid_operations", "trim_to_roof", *REMOVALS):
        for instance in (first, second):
            instance.elements[PROP] = "Roof"
            if name in REMOVALS:
                instance.solid_links[(GUID, PROP)] = {"operation": "Subtraction", "linkFlags": {}}
                instance.element_trims[(GUID, PROP)] = "KeepInside"
    if name == "update_drawings":
        for instance in (first, second):
            database = instance.nav_databases["88888888-8888-4888-8888-000000000013"]
            instance.layout_drawings[database] = ["D2000000-0000-4000-8000-000000000002"]
    if name == "create_composites":
        for instance in (first, second):
            row = BUILDING_MATERIALS_FIXTURE["get_building_materials"]["buildingMaterials"][1]
            instance.building_materials[row["attributeId"]["guid"]] = deepcopy(row)
    if name in ("apply_favorites", "update_favorites_from_elements"):
        for instance in (first, second):
            instance.favorites["Wall"] = ["Parede padrão"]
    if name == "unlock_elements":
        for instance in (first, second):
            instance.locked_elements.add(GUID)
    if name == "update_zones":
        for instance in (first, second):
            instance.elements[PROP] = "Zone"
    if name == "save_room_plan_views":
        for instance in (first, second):
            instance.elements[PROP] = "Zone"
            instance.details[PROP] = {"type": "Zone", "floorIndex": 0}
            instance.bounding_boxes_3d[PROP] = {
                "boundingBox3D": {"xMin": 0, "yMin": 0, "zMin": 0, "xMax": 4, "yMax": 3, "zMax": 3}
            }
            for key in ("Zone_ZoneName", "Zone_ZoneNumber", "Zone_CalculatedArea"):
                instance.builtin_property_ids[key] = f"{len(key):08d}-0000-4000-8000-000000000000"
    if name == "delete_elements":
        for instance in (first, second):
            instance.project_name = ""
            instance.details[GUID] = {"type": "Wall", "floorIndex": 0, "layerIndex": 1}
    async with client(first, second) as c:
        if name in {
            "list_camera_paths",
            "begin_model_task",
            "finish_model_task",
            "create_camera_paths_from_views",
        }:
            from archicad_mcp_aberto.connection import AddOnError

            with pytest.raises((AddOnError, ValueError)):
                await TARGETED[name](c, port=port, **deepcopy(INPUTS[name]))
            selected, untouched = (first, second) if port == 19723 else (second, first)
            assert selected.calls and not untouched.calls
            assert not any(
                command.startswith(("Save", "Create")) for command in selected.own_addon_calls
            )
            return
        if name in {"save_project_as", "save_next_project_revision", "inspect_project_save"}:
            from archicad_mcp_aberto.connection import AddOnError

            with pytest.raises(AddOnError):
                await TARGETED[name](c, port=port, **deepcopy(INPUTS[name]))
            selected, untouched = (first, second) if port == 19723 else (second, first)
            assert selected.own_addon_calls == ["GetProjectSaveContext"]
            assert not untouched.calls
            return
        if name in {"inspect_object_replacements", "replace_object_libraries"}:
            from archicad_mcp_aberto.connection import AddOnError

            # General fake intentionally lacks the new native command. Dedicated
            # contract stubs test replacement separately; here verify routing and
            # fail-closed behavior with an old companion add-on.
            with pytest.raises(AddOnError):
                await TARGETED[name](c, port=port, **deepcopy(INPUTS[name]))
            selected, untouched = (first, second) if port == 19723 else (second, first)
            assert selected.own_addon_calls == ["GetObjectReplacementData"]
            assert untouched.calls == untouched.own_addon_calls == []
            assert selected.elements == untouched.elements == {GUID: "Wall"}
            return
        result = await TARGETED[name](c, port=port, **deepcopy(INPUTS[name]))
    if isinstance(result, tuple):  # shoot_3d_scenes: (report, images)
        result = result[0]
    selected, untouched = (first, second) if port == 19723 else (second, first)
    result_port = result["target"]["port"] if "target" in result else result["port"]
    assert result_port == port
    assert selected.calls and untouched.calls == []
    expected_type = "Object" if name in {"get_gdl_parameters", "set_gdl_parameters"} else "Wall"
    expected_type = MODIFY_TYPES.get(name, expected_type)
    extra = {
        "create_groups": {PROP: "Wall"},
        "update_zones": {PROP: "Zone"},
        "save_room_plan_views": {PROP: "Zone"},
        "create_solid_operations": {PROP: "Roof"},
        "trim_to_roof": {PROP: "Roof"},
        "remove_solid_operations": {PROP: "Roof"},
        "remove_trims": {PROP: "Roof"},
    }.get(name, {})
    assert selected.elements == untouched.elements == {GUID: expected_type, **extra}
    assert not any("Create" in command or "Save" in command for command in selected.tapir_calls)


@pytest.mark.parametrize("reversed_ports", [False, True])
async def test_resolver_never_guesses_even_after_an_explicit_call(reversed_ports):
    first, second = instances()
    async with client(first, second, reversed_ports) as c:
        assert await resolve_port(c, 19724) == 19724
        with pytest.raises(AmbiguousTarget):
            await resolve_port(c, None)
        assert await resolve_port(c, 19723) == 19723


@pytest.mark.parametrize("name", ["discover_archicad", "tapir_status"])
async def test_instance_inventory_tools_report_both_without_selecting(name):
    first, second = instances()
    async with client(first, second) as c:
        result = await getattr(read, name)(c)
    assert {item["port"] for item in result["instances"]} == {19723, 19724}
    assert result["status"] == "connected"


@pytest.mark.parametrize("name", [n for n in TARGETED if n.startswith("create_")])
async def test_write_apply_requires_explicit_port_before_dispatch(name, tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path / "receipts"))
    first, second = instances()
    if name in {"create_windows", "create_doors", "create_associative_dimensions"}:
        second.details[GUID] = deepcopy(CREATE_WALLS_FIXTURE["wall_details"])
    if name == "set_layer_settings":
        for instance in (first, second):
            instance.layers[2] = "Editable"
    if name == "create_groups":
        second.elements[PROP] = "Wall"
    if name in ("create_solid_operations", "trim_to_roof"):
        second.elements[PROP] = "Roof"
    if name == "create_composites":
        row = BUILDING_MATERIALS_FIXTURE["get_building_materials"]["buildingMaterials"][1]
        second.building_materials[row["attributeId"]["guid"]] = deepcopy(row)
    arguments = deepcopy(INPUTS[name])
    if name == "create_camera_paths_from_views":

        async def camera_plan(c, port, path_name, view_guids):
            return {
                "target": {"port": port},
                "path_name": path_name,
                "groups": [],
                "skipped": [],
                "note": "Target selection fixture",
            }

        monkeypatch.setattr(camera_paths, "_plan", camera_plan)
    async with client(first, second) as c:
        preview = await TARGETED[name](c, port=19724, **arguments)
        first.calls.clear()
        second.calls.clear()
        first.tapir_calls.clear()
        second.tapir_calls.clear()
        with pytest.raises(ValueError, match="explicit port"):
            await TARGETED[name](
                c, dry_run=False, confirmation_token=preview["confirmation_token"], **arguments
            )
    assert first.calls == second.calls == []
    assert first.tapir_calls == second.tapir_calls == []
    assert not (tmp_path / "receipts").exists()
