"""Opening-tool openings in walls and slabs, only with MockTransport."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import voids
from tests.unit.fake_archicad import CREATE_WALLS_FIXTURE, FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
WALL = "11111111-1111-1111-1111-111111111111"
SLAB = "22222222-2222-2222-2222-222222222222"
COLUMN = "33333333-3333-3333-3333-333333333333"
STORIES = [{"index": 0, "name": "Ground", "level": 0}, {"index": 1, "name": "Upper", "level": 3}]
INPUT = {"owner_guid": WALL, "base_point": {"x": 2, "y": 15, "z": 3.8}, "width": 0.9, "height": 1.2}


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    fake = FakeArchicad(
        19723,
        stories=deepcopy(STORIES),
        elements={WALL: "Wall", SLAB: "Slab", COLUMN: "Column"},
        **kwargs,
    )
    wall = deepcopy(CREATE_WALLS_FIXTURE["wall_details"])
    wall["floorIndex"] = 1
    fake.details = {
        WALL: wall,
        SLAB: {"type": "Slab", "floorIndex": 0, "layerIndex": 1, "details": {}},
        COLUMN: {"type": "Column", "floorIndex": 0, "layerIndex": 1, "details": {}},
    }
    return fake


async def apply(c, entries):
    preview = await voids.create_openings(c, entries, 19723)
    return await voids.create_openings(c, entries, 19723, False, preview["confirmation_token"])


async def test_preview_then_create_and_verify_against_the_host():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await voids.create_openings(c, [{**INPUT, "owner_guid": WALL.lower()}], 19723)
        item = preview["items"][0]
        assert item["owner_type"] == "Wall"
        assert item["parameters"] == {
            "ownerElementId": {"guid": WALL},
            "basePoint": {"x": 2, "y": 15, "z": 3.8},
            "width": 0.9,
            "height": 1.2,
        }
        assert "CreateOpenings" not in fake.tapir_calls
        result = await voids.create_openings(
            c, [INPUT], 19723, False, preview["confirmation_token"]
        )
    assert result["status"] == "verified"
    item = result["items"][0]
    assert item["opening_receipt_id"] and item["after"]["type"] == "Opening"
    request = next(r for r in fake.tapir_requests if r["command"] == "GetConnectedElements")
    assert request["parameters"]["connectedElementType"] == "Opening"
    assert not any("Save" in cmd or "Delete" in cmd for cmd in fake.tapir_calls)


async def test_several_openings_in_one_wall_and_one_slab():
    fake = model()
    second = {**INPUT, "base_point": {"x": 3, "y": 15, "z": 3.8}}
    slab = {**INPUT, "owner_guid": SLAB, "base_point": {"x": 1, "y": 1, "z": 0}}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [INPUT, second, slab])
    assert [i["status"] for i in result["items"]] == ["verified"] * 3
    assert [i["owner_type"] for i in result["items"]] == ["Wall", "Wall", "Slab"]
    request = next(r for r in fake.tapir_requests if r["command"] == "GetConnectedElements")
    assert len(request["parameters"]["elements"]) == 2


async def test_opening_missing_from_its_host_fails_verification():
    fake = model(opening_unhosted=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [INPUT])
    item = result["items"][0]
    assert item["status"] == "verification_failed" and item["mismatches"] == ["owner"]


async def test_unreadable_host_list_leaves_the_opening_unverified():
    fake = model(connected_error=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [INPUT])
    item = result["items"][0]
    assert item["status"] == "unverified" and "Host openings not read" in item["error"]


async def test_per_item_error_keeps_the_others():
    fake = model(create_errors={0: {"error": {"code": -1, "message": "Failed to create opening."}}})
    second = {**INPUT, "base_point": {"x": 3, "y": 15, "z": 3.8}}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [INPUT, second])
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]


async def test_refusals_before_writing():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        tool = voids.create_openings
        with pytest.raises(ValueError, match="not a wall or slab"):
            await tool(c, [{**INPUT, "owner_guid": COLUMN}], 19723)
        with pytest.raises(ValueError, match="does not exist"):
            await tool(c, [{**INPUT, "owner_guid": "44444444-4444-4444-4444-444444444444"}], 19723)
        with pytest.raises(ValidationError):
            await tool(c, [{**INPUT, "width": 0}], 19723)
        with pytest.raises(ValidationError):
            await tool(c, [{**INPUT, "base_point": {"x": "inf", "y": 0, "z": 0}}], 19723)
        with pytest.raises(ValueError, match="between 1 and 50"):
            await tool(c, [INPUT] * 51, 19723)
    assert "CreateOpenings" not in fake.tapir_calls
