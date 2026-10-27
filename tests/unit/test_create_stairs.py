"""create_stairs: straight stairs by Tapir 1.7.0 CreateStairs (shapes from the source)."""

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import stairs
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
STORIES = [{"index": 0, "name": "Térreo", "level": 0.0}, {"index": 1, "name": "1º", "level": 3.0}]
STAIR = {
    "start": {"x": 0, "y": 0},
    "end": {"x": 4, "y": 0},
    "floor_index": 0,
    "base_level": 0.0,
    "total_height": 2.88,
    "flight_width": 1.1,
    "risers": 16,
}


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    return FakeArchicad(19723, stories=[dict(s) for s in STORIES], **kwargs)


def sent(fake):
    return next(r for r in fake.tapir_requests if r["command"] == "CreateStairs")["parameters"]


async def apply(c, items):
    preview = await stairs.create_stairs(c, items, 19723)
    return preview, await stairs.create_stairs(
        c, items, 19723, False, preview["confirmation_token"]
    )


async def test_straight_stair_is_created_and_checked_by_its_box():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(c, [STAIR])
    assert preview["items"][0]["status"] == "ready"
    data = sent(fake)["stairsData"][0]
    assert data == {
        "baseLinePoints": [{"x": 0, "y": 0}, {"x": 4, "y": 0}],
        "zCoordinate": 0.0,
        "floorIndex": 0,
        "totalHeight": 2.88,
        "flightWidth": 1.1,
        "stepNum": 16,
    }
    item = result["items"][0]
    assert result["status"] == "verified", item.get("mismatches")
    assert fake.elements[item["element_guid"]] == "Stair"
    assert item["after_box"]["zMax"] == pytest.approx(2.88)


async def test_preview_sends_nothing():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        await stairs.create_stairs(c, [STAIR], 19723)
    assert "CreateStairs" not in fake.tapir_calls


async def test_left_out_sizes_come_from_the_tool_or_favorite():
    fake = model(favorites={"Stair": ["Escada Concreto"]})
    stair = {k: v for k, v in STAIR.items() if k not in ("total_height", "flight_width", "risers")}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(c, [{**stair, "favorite": "escada concreto"}])
    assert preview["items"][0]["favorite"] == "Escada Concreto"
    data = sent(fake)["stairsData"][0]
    assert data["favoriteName"] == "Escada Concreto"
    assert not {"totalHeight", "flightWidth", "stepNum"} & set(data)
    assert result["status"] == "verified"


async def test_box_below_the_base_fails_verification():
    fake = model(stair_box_drop=0.2)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [STAIR])
    item = result["items"][0]
    assert item["status"] == "verification_failed"
    assert "boundingBox3D.zMin" in item["mismatches"]


async def test_upper_story_stair_uses_absolute_base():
    fake = model()
    stair = {**STAIR, "floor_index": 1, "base_level": 3.0}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [stair])
    assert sent(fake)["stairsData"][0]["zCoordinate"] == 3.0
    assert result["status"] == "verified"
    assert fake.details[result["items"][0]["element_guid"]]["floorIndex"] == 1


async def test_failed_item_does_not_hide_the_others():
    fake = model(
        create_errors={0: {"error": {"code": -1, "message": "Failed to create new Stair"}}}
    )
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(
            c, [STAIR, {**STAIR, "start": {"x": 0, "y": 3}, "end": {"x": 4, "y": 3}}]
        )
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"end": {"x": 0.1, "y": 0}}, "at least 0.3 m"),
        ({"risers": 1}, "greater than or equal to 2"),
        ({"total_height": 0}, "greater than 0"),
        ({"favorite": "  "}, "favorite must not be blank"),
    ],
)
def test_bad_input_is_refused(change, message):
    with pytest.raises(ValidationError, match=message):
        stairs.StairCreate.model_validate({**STAIR, **change})


async def test_unknown_story_or_favorite_refused_in_preview():
    fake = model(favorites={"Stair": ["Escada Concreto"]})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="story 5 does not exist"):
            await stairs.create_stairs(c, [{**STAIR, "floor_index": 5}], 19723)
        with pytest.raises(ValueError, match="No Stair favorite named 'Escada Metálica'"):
            await stairs.create_stairs(c, [{**STAIR, "favorite": "Escada Metálica"}], 19723)
    assert "CreateStairs" not in fake.tapir_calls


async def test_more_than_twenty_refused():
    async with ArchicadClient(transport=fake_transport(model())) as c:
        with pytest.raises(ValueError, match="between 1 and 20"):
            await stairs.create_stairs(c, [STAIR] * 21, 19723)
