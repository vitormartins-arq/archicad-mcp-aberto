from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import edit, write
from tests.unit.fake_archicad import CREATE_WALLS_FIXTURE, FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
GUID = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    row = deepcopy(CREATE_WALLS_FIXTURE["wall_details"])
    return FakeArchicad(
        19723,
        elements={GUID: "Wall", OTHER: "Wall"},
        details={GUID: row, OTHER: deepcopy(row)},
        **kwargs,
    )


def wall(**changes):
    return {"guid": GUID, "height": 4.0, **changes}


async def apply(c, walls):
    preview = await edit.modify_walls(c, walls, 19723)
    return await edit.modify_walls(c, walls, 19723, False, preview["confirmation_token"])


async def test_preview_then_apply_all_allowed_fields():
    fake = model()
    inputs = [
        wall(
            thickness=0.3,
            bottomOffset=0.5,
            begCoordinate={"x": 2, "y": 3},
            endCoordinate={"x": 7, "y": 3},
        )
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await edit.modify_walls(c, inputs, 19723)
        assert preview["items"][0]["before"]["details"]["height"] == 3
        assert preview["items"][0]["new"]["height"] == 4
        assert "ModifyWalls" not in fake.tapir_calls
        result = await edit.modify_walls(c, inputs, 19723, False, preview["confirmation_token"])
        with pytest.raises(ValueError, match="consumed"):
            await edit.modify_walls(c, inputs, 19723, False, preview["confirmation_token"])
    assert result["status"] == "verified"
    details = result["items"][0]["after"]["details"]
    assert details["height"] == 4 and details["begThickness"] == 0.3
    assert details["bottomOffset"] == details["zCoordinate"] == 0.5
    assert details["begCoordinate"] == {"x": 2, "y": 3}
    assert result["items"][0]["wall_edit_receipt_id"]
    assert result["receipt_path"]


@pytest.mark.parametrize(
    "change",
    [
        {"height": 4.0},
        {"thickness": 0.3},
        {"bottomOffset": -0.2},
        {"begCoordinate": {"x": 1, "y": 15}},
        {"endCoordinate": {"x": 6, "y": 15}},
    ],
)
async def test_each_field_can_be_modified_alone(change):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [{"guid": GUID, **change}])
    assert result["status"] == "verified"
    request = next(r for r in fake.tapir_requests if r["command"] == "ModifyWalls")
    assert request["parameters"] == {"wallsWithDetails": [{"elementId": {"guid": GUID}, **change}]}


@pytest.mark.parametrize(
    "metadata",
    [
        {"arcAngle": 0.3},
        {"geometryType": "Trapezoid"},
        {"profileType": "Trapez"},
        {"geometryType": "Polygonal"},
    ],
)
async def test_curved_and_trapezoidal_refused(metadata):
    fake = model()
    fake.details[GUID]["details"].update(metadata)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="refused"):
            await edit.modify_walls(c, [wall()], 19723)
    assert "ModifyWalls" not in fake.tapir_calls


@pytest.mark.parametrize("reason", ["hotlink", "locked", "missing", "not-wall"])
async def test_unsafe_targets_refused(reason):
    fake = model()
    if reason == "hotlink":
        fake.details[GUID]["hotlinkId"] = {"guid": OTHER}
    elif reason == "locked":
        fake.locked_elements.add(GUID)
    elif reason == "missing":
        del fake.elements[GUID]
        del fake.details[GUID]
    else:
        fake.elements[GUID] = "Slab"
        fake.details[GUID]["type"] = "Slab"
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await edit.modify_walls(c, [wall()], 19723)
    assert "ModifyWalls" not in fake.tapir_calls


@pytest.mark.parametrize(
    "inputs",
    [
        [],
        [wall()] * 51,
        [wall(), wall()],
        [{"guid": GUID}],
        [wall(height=0)],
        [wall(thickness=-1)],
        [wall(bottomOffset=float("inf"))],
        [wall(structureType="Basic")],
        [wall(height=True)],
    ],
)
async def test_limits_and_unknown_fields_before_network(inputs):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await edit.modify_walls(c, inputs)
    assert not fake.calls


async def test_zero_length_result_refused():
    fake = model()
    endpoint = deepcopy(fake.details[GUID]["details"]["endCoordinate"])
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="zero length"):
            await edit.modify_walls(c, [wall(begCoordinate=endpoint)], 19723)
    assert "ModifyWalls" not in fake.tapir_calls


async def test_composite_direct_thickness_refused():
    fake = model()
    fake.details[GUID]["details"]["structureType"] = "Composite"
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="Basic"):
            await edit.modify_walls(c, [wall(thickness=0.2)], 19723)


async def test_partial_native_error():
    fake = model(
        modify_wall_errors={1: {"success": False, "error": {"code": -1, "message": "Refused"}}}
    )
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [wall(), wall(guid=OTHER)])
    assert [i["status"] for i in result["items"]] == ["verified", "failed"]
    assert len({i["wall_edit_receipt_id"] for i in result["items"]}) == 2


async def test_ignored_edit_fails_verification():
    async with ArchicadClient(transport=fake_transport(model(modify_wall_ignored=True))) as c:
        result = await apply(c, [wall()])
    assert result["items"][0]["status"] == "verification_failed"


async def test_changed_existing_wall_requires_new_preview():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await edit.modify_walls(c, [wall()], 19723)
        fake.details[GUID]["details"]["height"] = 6
        with pytest.raises(ValueError, match="changed"):
            await edit.modify_walls(c, [wall()], 19723, False, preview["confirmation_token"])
    assert "ModifyWalls" not in fake.tapir_calls


async def test_lost_response_unknown_and_consumed():
    fake = model(lose_modify_wall_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await edit.modify_walls(c, [wall()], 19723)
        result = await edit.modify_walls(c, [wall()], 19723, False, preview["confirmation_token"])
        with pytest.raises(ValueError, match="consumed"):
            await edit.modify_walls(c, [wall()], 19723, False, preview["confirmation_token"])
    assert result["items"][0]["status"] == "unknown"
    assert fake.tapir_calls.count("ModifyWalls") == 1


async def test_journal_failure_prevents_dispatch(monkeypatch):
    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(write, "_journal", fail)
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(OSError):
            await apply(c, [wall()])
    assert "ModifyWalls" not in fake.tapir_calls
