"""Wall thickness dimensions, only with MockTransport."""

from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import wall_dimensions
from tests.unit.fake_archicad import CREATE_WALLS_FIXTURE, FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
WALL = "11111111-1111-1111-1111-111111111111"
SLAB = "22222222-2222-2222-2222-222222222222"
CURVED = "33333333-3333-3333-3333-333333333333"
STORIES = [{"index": 0, "name": "Ground", "level": 0}, {"index": 1, "name": "Upper", "level": 3}]


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    fake = FakeArchicad(
        19723,
        stories=deepcopy(STORIES),
        elements={WALL: "Wall", SLAB: "Slab", CURVED: "Wall"},
        **kwargs,
    )
    wall = deepcopy(CREATE_WALLS_FIXTURE["wall_details"])
    wall["floorIndex"] = 1
    curved = deepcopy(wall)
    curved["details"].update(geometryType="Arc", arcAngle=1.0)
    slab = {"type": "Slab", "floorIndex": 0, "layerIndex": 1, "details": {}}
    fake.details = {WALL: wall, CURVED: curved, SLAB: slab}
    return fake


async def apply(c, entries):
    preview = await wall_dimensions.create_wall_thickness_dimensions(c, entries, 19723)
    return await wall_dimensions.create_wall_thickness_dimensions(
        c, entries, 19723, False, preview["confirmation_token"]
    )


async def test_default_line_crosses_the_wall_middle_and_is_read_back_on_its_story():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await wall_dimensions.create_wall_thickness_dimensions(
            c, [{"wall_guid": WALL.lower()}], 19723
        )
        item = preview["items"][0]
        # Fixture wall runs from (0, 15) to (4, 15): middle (2, 15), perpendicular is +y.
        assert item["parameters"] == {
            "wallId": {"guid": WALL},
            "referencePoint": {"x": 2.0, "y": 15.0},
            "direction": {"x": 0.0, "y": 1.0},
        }
        assert "CreateWallThicknessDimensions" not in fake.tapir_calls
        result = await wall_dimensions.create_wall_thickness_dimensions(
            c, [{"wall_guid": WALL}], 19723, False, preview["confirmation_token"]
        )
    assert result["status"] == "verified"
    item = result["items"][0]
    assert item["dimension_receipt_id"] and item["after"]["type"] == "Dimension"
    assert item["after"]["floorIndex"] == 1
    assert not any("Save" in cmd or "Delete" in cmd for cmd in fake.tapir_calls)


async def test_explicit_point_and_direction_are_sent_as_given():
    fake = model()
    entry = {"wall_guid": WALL, "reference_point": {"x": 1, "y": 14}, "direction": {"x": 0, "y": 2}}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [entry])
    payload = next(
        r["parameters"]
        for r in fake.tapir_requests
        if r["command"] == "CreateWallThicknessDimensions"
    )
    assert payload == {
        "dimensionsData": [
            {
                "wallId": {"guid": WALL},
                "referencePoint": {"x": 1, "y": 14},
                "direction": {"x": 0, "y": 2},
            }
        ]
    }
    assert result["status"] == "verified"


async def test_dimension_on_another_story_fails_verification():
    fake = model(dimension_floor_shift=1)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [{"wall_guid": WALL}])
    item = result["items"][0]
    assert item["status"] == "verification_failed" and item["mismatches"] == ["floorIndex"]


async def test_refusals_before_writing():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        tool = wall_dimensions.create_wall_thickness_dimensions
        with pytest.raises(ValueError, match="not a wall"):
            await tool(c, [{"wall_guid": SLAB}], 19723)
        with pytest.raises(ValueError, match="curved wall"):
            await tool(c, [{"wall_guid": CURVED}], 19723)
        with pytest.raises(ValueError, match="non-zero"):
            await tool(c, [{"wall_guid": WALL, "direction": {"x": 0, "y": 0}}], 19723)
        with pytest.raises(ValueError, match="only once"):
            await tool(c, [{"wall_guid": WALL}, {"wall_guid": WALL.lower()}], 19723)
        with pytest.raises(ValueError, match="badly formed"):
            await tool(c, [{"wall_guid": "not-a-guid"}], 19723)
    assert "CreateWallThicknessDimensions" not in fake.tapir_calls


async def test_curved_wall_with_explicit_direction_is_allowed():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [{"wall_guid": CURVED, "direction": {"x": 1, "y": 0}}])
    assert result["status"] == "verified"
