"""P-005: target selection against MockTransport only; never a real Archicad."""

import inspect
from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import AmbiguousTarget, ArchicadClient, resolve_port
from archicad_mcp_aberto.server import create_server
from archicad_mcp_aberto.tools import (
    attribute_properties,
    attributes,
    classifications,
    documents,
    drafting,
    edit,
    favorites,
    gateway,
    interior_elevations,
    issues,
    keynotes,
    labels,
    layer_settings,
    layers,
    locks,
    meshes,
    modify,
    morphs,
    navigator,
    openings,
    project_info,
    property_definitions,
    read,
    renames,
    roofs,
    sections,
    selection,
    texts,
    views,
    write,
    zones,
)
from tests.unit.fake_archicad import CREATE_WALLS_FIXTURE, FakeArchicad, fake_transport
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
    "modify_roofs": "Roof",
    "modify_texts": "Text",
    "modify_labels": "Label",
    "modify_meshes": "Mesh",
}
INPUTS = {
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
    "lock_elements": {"element_guids": [GUID]},
    "unlock_elements": {"element_guids": [GUID]},
    "update_zones": {},
    "list_property_groups": {},
    "create_worksheets": {"worksheets": [{"name": "Rascunho", "reference_id": "W2"}]},
    "create_details": {"details": [{"name": "Detalhe da escada", "reference_id": "D1"}]},
    "create_layouts": {"layouts": [{"name": "Cortes", "master": "A3 Paisagem"}]},
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
    "get_bounding_boxes": {"element_ids": [GUID]},
    "list_keynotes": {},
    "create_keynote_folders": {"folders": [{"key": "01", "title": "Paredes"}]},
    "create_keynote_items": {"items": [{"key": "01.01", "title": "Alvenaria"}]},
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
}
TARGETED = {
    name: function
    for module in (
        attribute_properties,
        attributes,
        classifications,
        documents,
        drafting,
        renames,
        edit,
        favorites,
        gateway,
        interior_elevations,
        issues,
        keynotes,
        labels,
        layer_settings,
        layers,
        locks,
        meshes,
        modify,
        morphs,
        navigator,
        openings,
        project_info,
        property_definitions,
        read,
        roofs,
        sections,
        selection,
        texts,
        views,
        write,
        zones,
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
    if name in {"modify_walls", "create_windows", "create_doors"}:
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
    if name == "apply_favorites":
        for instance in (first, second):
            instance.favorites["Wall"] = ["Parede padrão"]
    if name == "unlock_elements":
        for instance in (first, second):
            instance.locked_elements.add(GUID)
    if name == "update_zones":
        for instance in (first, second):
            instance.elements[PROP] = "Zone"
    if name == "delete_elements":
        for instance in (first, second):
            instance.project_name = ""
            instance.details[GUID] = {"type": "Wall", "floorIndex": 0, "layerIndex": 1}
    async with client(first, second) as c:
        result = await TARGETED[name](c, port=port, **deepcopy(INPUTS[name]))
    selected, untouched = (first, second) if port == 19723 else (second, first)
    result_port = result["target"]["port"] if "target" in result else result["port"]
    assert result_port == port
    assert selected.calls and untouched.calls == []
    expected_type = "Object" if name in {"get_gdl_parameters", "set_gdl_parameters"} else "Wall"
    expected_type = MODIFY_TYPES.get(name, expected_type)
    extra = {"create_groups": {PROP: "Wall"}, "update_zones": {PROP: "Zone"}}.get(name, {})
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
    if name in {"create_windows", "create_doors"}:
        second.details[GUID] = deepcopy(CREATE_WALLS_FIXTURE["wall_details"])
    if name == "set_layer_settings":
        for instance in (first, second):
            instance.layers[2] = "Editable"
    if name == "create_groups":
        second.elements[PROP] = "Wall"
    arguments = deepcopy(INPUTS[name])
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
