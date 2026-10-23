import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.server import create_server
from archicad_mcp_aberto.tools import read
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio

WALL = "11111111-1111-1111-1111-111111111111"
SLAB = "22222222-2222-2222-2222-222222222222"
PROP = "33333333-3333-3333-3333-333333333333"
MISSING = "44444444-4444-4444-4444-444444444444"


def model(**kw):
    return FakeArchicad(
        19723,
        elements={WALL: "Wall", SLAB: "Slab"},
        selection=[WALL],
        properties={PROP: "Fabricante"},
        **kw,
    )


def client(*instances):
    return ArchicadClient(transport=fake_transport(*instances))


async def test_discover_counts():
    async with client(model()) as c:
        result = await read.discover_archicad(c)
    inst = result["instances"][0]
    assert result["status"] == "connected"
    assert (inst["element_count"], inst["selected_count"]) == (2, 1)


async def test_discover_waiting():
    async with client() as c:
        assert (await read.discover_archicad(c))["status"] == "waiting_for_archicad"


async def test_list_elements_by_type_and_page():
    async with client(model()) as c:
        walls = await read.list_elements(c, element_type="Wall")
        page = await read.list_elements(c, offset=1, limit=1)
    assert walls["total"] == 1
    assert page["total"] == 2 and len(page["elements"]) == 1
    with pytest.raises(ValueError):
        async with client(model()) as c:
            await read.list_elements(c, limit=501)


async def test_selection_is_read_only():
    fake = model()
    async with client(fake) as c:
        result = await read.get_selection(c)
    assert result["elements"][0]["elementId"]["guid"] == WALL
    assert not any("Select" in call and "Get" not in call for call in fake.calls)


async def test_list_properties_returns_definitions():
    async with client(model()) as c:
        result = await read.list_properties(c, limit=5)
    assert result["total"] == 1
    assert result["propertyDefinitions"][0]["propertyDefinition"]["name"] == "Fabricante"


async def test_property_values_keep_per_item_errors():
    async with client(model()) as c:
        result = await read.get_properties(c, [WALL, MISSING], [PROP])
    rows = result["propertyValuesForElements"]
    assert "propertyValues" in rows[0] and "error" in rows[1]


async def test_guid_validation():
    async with client(model()) as c:
        with pytest.raises(ValueError):
            await read.get_properties(c, ["not-a-guid"], [PROP])
        with pytest.raises(ValueError):
            await read.get_properties(c, [WALL], [])


async def test_details_skip_floor_plan_polygons_by_default():
    async with client(model()) as c:
        default = await read.get_element_details(c, [WALL])
        heavy = await read.get_element_details(c, [WALL], fields=["type", "floorPlanPolygons"])
        with pytest.raises(ValueError):
            await read.get_element_details(c, [WALL], fields=["nope"])
    assert "floorPlanPolygons" not in default["detailsOfElements"][0]
    assert heavy["detailsOfElements"][0]["floorPlanPolygons"] == []
    assert "no floor plan polygons" in heavy["note"]


async def test_floor_plan_polygons_pass_through():
    square = [{"coordinates": [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 0.1}]}]
    async with client(model(cut_fills={WALL: square})) as c:
        result = await read.get_element_details(c, [WALL], fields=["floorPlanPolygons"])
    assert result["detailsOfElements"][0]["floorPlanPolygons"] == square
    assert "note" not in result


async def test_tapir_status_per_instance():
    async with client(model(), FakeArchicad(19724, tapir_version=None)) as c:
        result = await read.tapir_status(c)
    state = {i["port"]: i["tapir_loaded"] for i in result["instances"]}
    assert state == {19723: True, 19724: False}


async def test_stories_and_project():
    async with client(model(project_name="Casa A")) as c:
        assert (await read.get_project_info(c))["projectName"] == "Casa A"
        assert (await read.get_stories(c))["stories"][0]["name"] == "Térreo"


async def test_server_registers_eleven_read_only_tools_and_wall_creation():
    server = create_server(lambda: client(model()))
    tools = await server.list_tools()
    assert len(tools) == 112
    writes = {
        "create_walls",
        "create_slabs",
        "create_columns",
        "create_beams",
        "create_roofs",
        "create_texts",
        "create_labels",
        "create_keynote_labels",
        "modify_morphs",
        "create_lines",
        "create_polylines",
        "create_splines",
        "create_hotspots",
        "create_arcs",
        "create_circles",
        "create_fills",
        "set_classifications",
        "create_layers",
        "create_zone_categories",
        "create_stairs",
        "set_element_layers",
        "create_groups",
        "set_project_info_fields",
        "apply_favorites",
        "select_elements",
        "highlight_elements",
        "create_zones",
        "create_objects",
        "move_elements",
        "rotate_elements",
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
        "set_property_values",
        "set_gdl_parameters",
        "delete_elements",
        "lock_elements",
        "unlock_elements",
        "update_zones",
        "create_property_groups",
        "create_properties",
        "create_worksheets",
        "create_details",
        "create_layouts",
        "rename_items",
        "modify_labels",
        "create_meshes",
        "modify_meshes",
        "set_view_settings",
        "set_layer_settings",
        "create_issues",
        "attach_elements_to_issue",
        "add_comment_to_issue",
        "create_view_map_folders",
        "clone_to_view_map",
        "create_classification_items",
        "create_sections",
        "create_favorites_from_elements",
        "set_attribute_property_values",
        "create_interior_elevations",
        "create_keynote_folders",
        "create_keynote_items",
        "create_morphs",
        "create_wall_thickness_dimensions",
        "create_associative_dimensions",
        "create_lamps",
        "create_openings",
        "shoot_3d_scenes",
        "save_3d_scenes",
        "create_composites",
        "create_drawings",
        "add_stories",
        "create_design_options",
        "move_to_design_options",
    }
    reads = [t for t in tools if t.name not in writes]
    creation = next(t for t in tools if t.name == "create_walls")
    assert len(reads) == 30
    assert all(t.annotations and t.annotations.readOnlyHint for t in reads)
    assert creation.annotations and not creation.annotations.readOnlyHint
    assert creation.annotations.destructiveHint and not creation.annotations.idempotentHint
    move = next(t for t in tools if t.name == "move_elements")
    assert move.annotations and not move.annotations.readOnlyHint
    assert creation.inputSchema["properties"]["dry_run"]["default"] is True
