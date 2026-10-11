from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import write
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
GUID = "11111111-1111-1111-1111-111111111111"
PROP = "22222222-2222-2222-2222-222222222222"


def args(operation):
    return (
        {"moves": [{"guid": GUID, "vector": {"x": 1, "y": 0}}]}
        if operation == "move_elements"
        else {"changes": [{"element_guid": GUID, "property_guid": PROP, "value": "new"}]}
        if operation == "set_property_values"
        else {"element_guids": [GUID]}
    )


def model():
    return FakeArchicad(
        19723,
        project_name="",
        elements={GUID: "Wall"},
        details={GUID: {"type": "Wall", "floorIndex": 0, "layerIndex": 1}},
        properties={PROP: "Test"},
    )


@pytest.mark.parametrize(
    "operation",
    sorted(write.NAMED_PREVIEWS & {"move_elements", "set_property_values", "delete_elements"}),
)
async def test_preview_names_one_layer_call(operation):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await getattr(write, operation)(c, port=19723, **args(operation))
    item = preview["items"][0]
    assert item["floorIndex"] == 0 and item["floorName"] == "Térreo"
    assert item["layerIndex"] == 1 and item["layerName"] == "Walls"
    requests = [r for r in fake.tapir_requests if r["command"] == "GetAttributesByType"]
    assert len(requests) == 1
    assert requests[0]["parameters"] == {"attributeType": "Layer"}


@pytest.mark.parametrize(
    "operation",
    sorted(write.NAMED_PREVIEWS & {"move_elements", "set_property_values", "delete_elements"}),
)
async def test_names_change_does_not_consume_or_invalidate_token(operation, tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await getattr(write, operation)(c, port=19723, **args(operation))
        fake.layers[1] = "Renamed layer"
        fake.stories[0]["name"] = "Renamed story"
        result = await getattr(write, operation)(
            c,
            port=19723,
            dry_run=False,
            confirmation_token=preview["confirmation_token"],
            **args(operation),
        )
    assert result["status"] == "verified"
    assert result["items"][0]["layerName"] == "Renamed layer"


@pytest.mark.parametrize(
    "operation",
    sorted(write.NAMED_PREVIEWS & {"move_elements", "set_property_values", "delete_elements"}),
)
async def test_missing_names_are_null(operation):
    fake = model()
    fake.layers = {}
    fake.stories[0].pop("name")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await getattr(write, operation)(c, port=19723, **args(operation))
    assert preview["items"][0]["floorName"] is None
    assert preview["items"][0]["layerName"] is None


async def test_name_lookup_error_does_not_refuse_preview(monkeypatch):
    original = FakeArchicad._tapir

    def fail(self, params):
        if params["addOnCommandId"]["commandName"] == "GetAttributesByType":
            return {"succeeded": False, "error": {"code": 4010, "message": "Unavailable"}}
        return original(self, params)

    monkeypatch.setattr(FakeArchicad, "_tapir", fail)
    async with ArchicadClient(transport=fake_transport(model())) as c:
        preview = await write.move_elements(c, port=19723, **args("move_elements"))
    assert preview["items"][0]["layerName"] is None


async def test_indices_still_part_of_confirmation_identity():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await write.set_property_values(c, port=19723, **args("set_property_values"))
        changed = deepcopy(preview)
        changed["items"][0]["layerIndex"] = 5
        assert write._plan_digest(preview) != write._plan_digest(changed)
