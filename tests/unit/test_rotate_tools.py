import math

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import edit
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
GUID = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def rotation(**changes):
    return {"guid": GUID, "center": {"x": 1, "y": 1}, "angle": math.pi / 2, **changes}


def model(**changes):
    return FakeArchicad(
        19723,
        elements={GUID: "Object", OTHER: "Object"},
        details={
            GUID: {
                "type": "Object",
                "floorIndex": 0,
                "layerIndex": 1,
                "details": {"origin": {"x": 3, "y": 1, "z": 2}, "angle": 0},
            },
            OTHER: {"type": "Object", "floorIndex": 0, "layerIndex": 1},
        },
        **changes,
    )


async def apply(c, rotations):
    preview = await edit.rotate_elements(c, rotations, 19723)
    return await edit.rotate_elements(c, rotations, 19723, False, preview["confirmation_token"])


async def test_preview_and_verify_object_origin_and_angle():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await edit.rotate_elements(c, [rotation()], 19723)
        assert "RotateElements" not in fake.tapir_calls
        assert preview["items"][0]["floorName"] == "Térreo"
        result = await edit.rotate_elements(
            c, [rotation()], 19723, False, preview["confirmation_token"]
        )
        with pytest.raises(ValueError, match="consumed"):
            await edit.rotate_elements(c, [rotation()], 19723, False, preview["confirmation_token"])
    assert result["status"] == "verified"
    after = result["items"][0]["after"]["details"]
    assert after["origin"]["x"] == pytest.approx(1)
    assert after["origin"]["y"] == pytest.approx(3)
    assert after["origin"]["z"] == 2
    assert after["angle"] == pytest.approx(math.pi / 2)
    assert result["receipt_path"]


@pytest.mark.parametrize("angle", [-math.pi / 4, math.pi / 3, math.pi * 2.5])
async def test_arbitrary_angle_when_details_available(angle):
    async with ArchicadClient(transport=fake_transport(model())) as c:
        assert (await apply(c, [rotation(angle=angle)]))["status"] == "verified"


async def test_box_quarter_turn_verifies():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [rotation(guid=OTHER)])
    assert result["status"] == "verified"
    assert result["items"][0]["verification"] == "box"


async def test_arbitrary_box_only_rotation_refused():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="Cannot verify"):
            await edit.rotate_elements(c, [rotation(guid=OTHER, angle=0.5)], 19723)
    assert "RotateElements" not in fake.tapir_calls


@pytest.mark.parametrize("reason", ["missing", "hotlink", "locked"])
async def test_unsafe_element_refused(reason):
    fake = model()
    if reason == "missing":
        del fake.elements[GUID]
        del fake.details[GUID]
    elif reason == "hotlink":
        fake.details[GUID]["hotlinkId"] = {"guid": OTHER}
    else:
        fake.locked_elements.add(GUID)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await edit.rotate_elements(c, [rotation()], 19723)
    assert "RotateElements" not in fake.tapir_calls


@pytest.mark.parametrize(
    "inputs",
    [
        [],
        [rotation()] * 51,
        [rotation(), rotation()],
        [rotation(angle=float("nan"))],
        [rotation(center={"x": True, "y": 0})],
    ],
)
async def test_input_limits(inputs):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await edit.rotate_elements(c, inputs)
    assert not fake.calls


async def test_partial_error():
    fake = model(rotate_errors={1: {"success": False, "error": {"code": -1, "message": "Refused"}}})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [rotation(), rotation(guid=OTHER)])
    assert [i["status"] for i in result["items"]] == ["verified", "failed"]
    assert len({i["rotation_receipt_id"] for i in result["items"]}) == 2


async def test_ignored_rotation_not_verified():
    async with ArchicadClient(transport=fake_transport(model(rotate_ignored=True))) as c:
        result = await apply(c, [rotation()])
    assert result["items"][0]["status"] == "verification_failed"


async def test_lost_response_unknown_consumes_token():
    fake = model(lose_rotate_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await edit.rotate_elements(c, [rotation()], 19723)
        result = await edit.rotate_elements(
            c, [rotation()], 19723, False, preview["confirmation_token"]
        )
        with pytest.raises(ValueError, match="consumed"):
            await edit.rotate_elements(c, [rotation()], 19723, False, preview["confirmation_token"])
    assert result["items"][0]["status"] == "unknown"


async def test_explicit_port_and_changed_plan():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await edit.rotate_elements(c, [rotation()], 19723)
        with pytest.raises(ValueError, match="explicit port"):
            await edit.rotate_elements(
                c, [rotation()], dry_run=False, confirmation_token=preview["confirmation_token"]
            )
        with pytest.raises(ValueError, match="changed"):
            await edit.rotate_elements(
                c, [rotation(angle=0.5)], 19723, False, preview["confirmation_token"]
            )
    assert "RotateElements" not in fake.tapir_calls
