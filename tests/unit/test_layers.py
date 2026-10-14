import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import layers
from tests.unit.fake_archicad import FakeArchicad, fake_transport, layer_guid

pytestmark = pytest.mark.anyio
WALL = "11111111-1111-4111-8111-111111111111"
SLAB = "22222222-2222-4222-8222-222222222222"
MISSING = "99999999-9999-4999-8999-999999999999"
STORIES = [
    {"index": 0, "name": "Térreo", "level": 0.0},
    {"index": 1, "name": "Superior", "level": 3.0},
]


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    return FakeArchicad(
        19723,
        elements={WALL: "Wall", SLAB: "Slab"},
        details={
            WALL: {"type": "Wall", "floorIndex": 1, "layerIndex": 1, "details": {}},
            SLAB: {"type": "Slab", "floorIndex": 0, "layerIndex": 1, "details": {}},
        },
        stories=[dict(s) for s in STORIES],
        **{
            "layers": {1: "Walls", 7: "Desenho"},
            "layer_flags": {7: {"isLocked": True, "intersectionGroupNr": 3}},
            **kwargs,
        },
    )


async def apply(tool, c, inputs):
    preview = await tool(c, inputs, 19723)
    return await tool(c, inputs, 19723, False, preview["confirmation_token"])


def sent(fake, command):
    return next(r for r in fake.tapir_requests if r["command"] == command)["parameters"]


async def test_list_layers_with_flags():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await layers.list_layers(c, 19723)
    assert result["total"] == 2
    desenho = next(r for r in result["layers"] if r["name"] == "Desenho")
    assert desenho == {
        "attributeId": {"guid": layer_guid(7)},
        "index": 7,
        "name": "Desenho",
        "isHidden": False,
        "isLocked": True,
        "isWireframe": False,
        "intersectionGroupNr": 3,
    }
    assert "fields" not in sent(fake, "GetLayers")


async def test_create_layers_preview_then_apply():
    fake = model()
    inputs = [{"name": "Cotas", "hidden": True, "intersection_group": 2}, {"name": "Mobiliário"}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await layers.create_layers(c, inputs, 19723)
        assert "CreateLayers" not in fake.tapir_calls
        token = preview["confirmation_token"]
        result = await layers.create_layers(c, inputs, 19723, False, token)
        with pytest.raises(ValueError, match="consumed"):
            await layers.create_layers(c, inputs, 19723, False, token)
    assert result["status"] == "verified"
    assert [i["status"] for i in result["items"]] == ["verified", "verified"]
    assert all(i["layer_receipt_id"] for i in result["items"])
    assert sent(fake, "CreateLayers") == {
        "layerDataArray": [
            {"name": "Cotas", "isHidden": True, "intersectionGroupNr": 2},
            {"name": "Mobiliário"},
        ],
        "overwriteExisting": False,
    }
    assert fake.layers[8] == "Cotas" and fake.layers[9] == "Mobiliário"


async def test_existing_or_repeated_name_is_refused_before_writing():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="already exists"):
            await layers.create_layers(c, [{"name": "desenho"}], 19723)
        with pytest.raises(ValueError, match="twice"):
            await layers.create_layers(c, [{"name": "Cotas"}, {"name": "COTAS"}], 19723)
    assert "CreateLayers" not in fake.tapir_calls


async def test_created_layer_read_back_mismatch():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await layers.create_layers(c, [{"name": "Cotas", "locked": True}], 19723)
        original = fake._tapir

        def stored(params):
            response = original(params)
            if params["addOnCommandId"]["commandName"] == "CreateLayers":
                fake.layer_flags[8]["isLocked"] = False
            return response

        fake._tapir = stored
        result = await layers.create_layers(
            c, [{"name": "Cotas", "locked": True}], 19723, False, preview["confirmation_token"]
        )
    assert result["items"][0]["status"] == "verification_failed"
    assert result["items"][0]["mismatches"] == ["isLocked"]


async def test_create_partial_error_and_lost_response():
    error = {"error": {"code": -1, "message": "Failed to create."}}
    fake = model(layer_create_errors={0: error})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(layers.create_layers, c, [{"name": "A"}, {"name": "B"}])
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]
    fake = model(lose_layer_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(layers.create_layers, c, [{"name": "A"}])
    assert result["items"][0]["status"] == "unknown"
    assert fake.tapir_calls.count("CreateLayers") == 1


@pytest.mark.parametrize(
    "item",
    [
        {"name": ""},
        {"name": " Cotas"},
        {"name": "Cotas "},
        {"name": "x" * 256},
        {"name": "Cotas", "intersection_group": -1},
        {"name": "Cotas", "color": "red"},
    ],
)
async def test_invalid_layers_refused_before_network(item):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await layers.create_layers(c, [item])
        with pytest.raises(ValueError):
            await layers.create_layers(c, [])
        with pytest.raises(ValueError):
            await layers.create_layers(c, [{"name": f"L{i}"} for i in range(51)])
    assert not fake.calls


async def test_move_elements_to_layers():
    fake = model()
    changes = [
        {"element_guid": WALL.lower(), "layer": "desenho"},
        {"element_guid": SLAB, "layer": "Walls"},
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await layers.set_element_layers(c, changes, 19723)
        assert "SetDetailsOfElements" not in fake.tapir_calls
        first, second = preview["items"]
        assert first["layerName"] == "Walls" and first["floorName"] == "Superior"
        assert first["new_layer"] == {"index": 7, "name": "Desenho"}
        assert not first["unchanged"] and second["unchanged"]
        result = await layers.set_element_layers(
            c, changes, 19723, False, preview["confirmation_token"]
        )
    assert result["status"] == "verified"
    assert sent(fake, "SetDetailsOfElements") == {
        "elementsWithDetails": [
            {"elementId": {"guid": WALL}, "details": {"layerIndex": 7}},
            {"elementId": {"guid": SLAB}, "details": {"layerIndex": 1}},
        ]
    }
    assert fake.details[WALL]["layerIndex"] == 7
    assert result["items"][0]["after"] == {"type": "Wall", "floorIndex": 1, "layerIndex": 7}


async def test_move_refusals():
    fake = model(locked_elements={WALL})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="Layer 'Cotas' does not exist"):
            await layers.set_element_layers(c, [{"element_guid": SLAB, "layer": "Cotas"}], 19723)
        with pytest.raises(ValueError, match="Locked"):
            await layers.set_element_layers(c, [{"element_guid": WALL, "layer": "Walls"}], 19723)
        with pytest.raises(ValueError, match="does not exist"):
            await layers.set_element_layers(c, [{"element_guid": MISSING, "layer": "Walls"}], 19723)
        with pytest.raises(ValueError, match="only once"):
            await layers.set_element_layers(
                c,
                [
                    {"element_guid": SLAB, "layer": "Walls"},
                    {"element_guid": SLAB.lower(), "layer": "Desenho"},
                ],
                19723,
            )
    fake = model(layers={1: "Desenho", 7: "desenho"})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="ambiguous"):
            await layers.set_element_layers(c, [{"element_guid": SLAB, "layer": "Desenho"}], 19723)
    assert "SetDetailsOfElements" not in fake.tapir_calls


async def test_move_ignored_failed_and_lost():
    fake = model(layer_move_ignored=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(
            layers.set_element_layers, c, [{"element_guid": WALL, "layer": "Desenho"}]
        )
    assert result["items"][0]["status"] == "verification_failed"
    assert result["items"][0]["mismatches"] == ["layerIndex"]
    error = {"success": False, "error": {"code": -1, "message": "Failed to change."}}
    fake = model(layer_move_errors={0: error})
    changes = [
        {"element_guid": WALL, "layer": "Desenho"},
        {"element_guid": SLAB, "layer": "Desenho"},
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(layers.set_element_layers, c, changes)
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]
    fake = model(lose_layer_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(
            layers.set_element_layers, c, [{"element_guid": WALL, "layer": "Desenho"}]
        )
        preview = await layers.set_element_layers(c, [{"element_guid": SLAB, "layer": "Walls"}])
        with pytest.raises(ValueError, match="explicit port"):
            await layers.set_element_layers(
                c,
                [{"element_guid": SLAB, "layer": "Walls"}],
                None,
                False,
                preview["confirmation_token"],
            )
    assert result["items"][0]["status"] == "unknown"
    assert fake.tapir_calls.count("SetDetailsOfElements") == 1
