import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import interior_elevations
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
STORIES = [
    {"index": 0, "name": "Térreo", "level": 0.0},
    {"index": 1, "name": "Superior", "level": 3.0},
]
ROOM = [{"x": 0, "y": 0}, {"x": 4, "y": 0}, {"x": 4, "y": 3}, {"x": 0, "y": 3}]
create = interior_elevations.create_interior_elevations


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    return FakeArchicad(19723, stories=[dict(s) for s in STORIES], **kwargs)


def elevation(**changes):
    return {"nodes": ROOM, "closed": True, "floor_index": 0, "name": "Sala", **changes}


async def apply(c, inputs):
    preview = await create(c, inputs, 19723)
    return await create(c, inputs, 19723, False, preview["confirmation_token"])


async def test_closed_room_preview_then_apply_verifies_story_and_project_map():
    fake = model()
    inputs = [
        elevation(depth=3.5, reference_id="VI-01"),
        elevation(name="Corredor", nodes=ROOM[:2], closed=False, floor_index=1),
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await create(c, inputs, 19723)
        assert "CreateInteriorElevations" not in fake.tapir_calls
        assert [i["segments"] for i in preview["items"]] == [4, 1]
        result = await create(c, inputs, 19723, False, preview["confirmation_token"])
    sent = next(r for r in fake.tapir_requests if r["command"] == "CreateInteriorElevations")
    first, second = sent["parameters"]["interiorElevationsData"]
    assert first == {
        "nodeCoordinates": [
            {"x": 0.0, "y": 0.0},
            {"x": 4.0, "y": 0.0},
            {"x": 4.0, "y": 3.0},
            {"x": 0.0, "y": 3.0},
            {"x": 0.0, "y": 0.0},
        ],
        "depth": 3.5,
        "name": "Sala",
        "floorIndex": 0,
        "id": "VI-01",
    }
    assert "id" not in second and second["depth"] == 1.0
    assert result["status"] == "verified"
    assert result["items"][0]["reference_ids"] == ["VI-01/1", "VI-01/2", "VI-01/3", "VI-01/4"]
    assert len(result["items"][1]["navigator_guids"]) == 1
    assert fake.tapir_calls.count("CreateInteriorElevations") == 1


async def test_existing_or_repeated_name_and_missing_story_refused():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        await apply(c, [elevation()])
        with pytest.raises(ValueError, match="already exists"):
            await create(c, [elevation(name="SALA")], 19723)
        with pytest.raises(ValueError, match="appears twice"):
            await create(c, [elevation(name="X"), elevation(name="x")], 19723)
        with pytest.raises(ValueError, match="story 5"):
            await create(c, [elevation(name="Y", floor_index=5)], 19723)
    assert fake.tapir_calls.count("CreateInteriorElevations") == 1


@pytest.mark.parametrize(
    "item",
    [
        elevation(nodes=ROOM[:1]),
        elevation(nodes=ROOM[:2]),  # closed needs 3 points
        elevation(nodes=[ROOM[0], ROOM[0], ROOM[1]], closed=False),
        elevation(nodes=[*ROOM, ROOM[0]]),  # closed repeats the first point itself
        elevation(nodes=[{"x": i, "y": 0} for i in range(51)], closed=False),
        elevation(name=" Sala"),
        elevation(reference_id=""),
        elevation(depth=0),
        elevation(extra=1),
    ],
)
async def test_invalid_inputs_refused_before_network(item):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await create(c, [item], 19723)
    assert fake.calls == []


async def test_missing_project_map_name_partial_error_and_lost_response():
    fake = model(section_stored_name="Outro")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [elevation()])
    assert result["items"][0]["status"] == "verification_failed"
    assert result["items"][0]["mismatches"] == ["navigator_name"]
    error = {"error": {"code": -1, "message": "Failed to create interior elevation."}}
    fake = model(create_errors={0: error})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [elevation(), elevation(name="Cozinha")])
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]
    fake = model(lose_section_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [elevation()])
    assert result["items"][0]["status"] == "unknown"
    assert fake.tapir_calls.count("CreateInteriorElevations") == 1


async def test_limits_and_explicit_port():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await create(c, [])
        with pytest.raises(ValueError):
            await create(c, [elevation(name=f"V{i}") for i in range(21)])
        preview = await create(c, [elevation()])
        with pytest.raises(ValueError, match="explicit port"):
            await create(c, [elevation()], None, False, preview["confirmation_token"])
