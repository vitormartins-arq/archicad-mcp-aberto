from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import write
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def beam(**changes):
    return {
        "start": {"x": 1, "y": 2},
        "end": {"x": 5, "y": 2},
        "floor_index": 0,
        "level": 3.5,
        "width": 0.2,
        "height": 0.4,
        **changes,
    }


async def apply(c, beams):
    preview = await write.create_beams(c, beams, 19723)
    return await write.create_beams(c, beams, 19723, False, preview["confirmation_token"])


async def test_preview_and_apply_absolute_level_on_upper_story():
    fake = FakeArchicad(19723, stories=[{"index": 1, "name": "Upper", "level": 3}])
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await write.create_beams(c, [beam(floor_index=1)], 19723)
        assert "CreateBeams" not in fake.tapir_calls
        p = preview["items"][0]["parameters"]
        assert p["width"] == 0.2 and p["height"] == 0.4
        assert p["isWidthAndHeightLinked"] is False
        result = await write.create_beams(
            c, [beam(floor_index=1)], 19723, False, preview["confirmation_token"]
        )
        with pytest.raises(ValueError, match="consumed"):
            await write.create_beams(
                c, [beam(floor_index=1)], 19723, False, preview["confirmation_token"]
            )
    assert result["status"] == "verified"
    assert result["items"][0]["after"]["details"]["level"] == 0.5
    assert result["items"][0]["beam_receipt_id"]
    assert result["receipt_path"]


@pytest.mark.parametrize(
    "changes",
    [
        {"end": {"x": 1, "y": 2}},
        {"width": 0},
        {"height": -1},
        {"level": float("nan")},
        {"start": {"x": float("inf"), "y": 0}},
        {"width": True},
        {"floor_index": "0"},
        {"unknown": 1},
    ],
)
async def test_invalid_inputs_before_network(changes):
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await write.create_beams(c, [beam(**changes)])
    assert fake.calls == []


@pytest.mark.parametrize("count", [0, 21])
async def test_batch_limit(count):
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as c:
        with pytest.raises(ValueError, match="1 and 20"):
            await write.create_beams(c, [beam()] * count)


async def test_missing_floor_refused():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="does not exist"):
            await write.create_beams(c, [beam(floor_index=9)], 19723)
    assert "CreateBeams" not in fake.tapir_calls


async def test_partial_error_and_receipts():
    fake = FakeArchicad(19723, create_errors={1: {"error": {"code": -1, "message": "Refused"}}})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [beam(), beam(end={"x": 8, "y": 2})])
    assert [i["status"] for i in result["items"]] == ["verified", "failed"]
    assert len({i["beam_receipt_id"] for i in result["items"]}) == 2


@pytest.mark.parametrize(
    "key,value",
    [
        ("width", 0.9),
        ("height", 0.9),
        ("zCoordinate", 0),
        ("level", 0),
        ("begCoordinate", {"x": 0, "y": 0}),
        ("endCoordinate", {"x": 0, "y": 0}),
        ("isSlanted", True),
        ("beamShape", "HorizontallyCurved"),
        ("profileId", {"guid": "11111111-1111-1111-1111-111111111111"}),
    ],
)
async def test_mismatch_not_verified(monkeypatch, key, value):
    original = FakeArchicad._tapir

    def altered(self, params):
        response = original(self, params)
        if params["addOnCommandId"]["commandName"] == "CreateBeams":
            for row in self.details.values():
                row["details"][key] = deepcopy(value)
        return response

    monkeypatch.setattr(FakeArchicad, "_tapir", altered)
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as c:
        result = await apply(c, [beam()])
    assert result["items"][0]["status"] == "verification_failed"


async def test_lost_response_unknown_and_consumed():
    fake = FakeArchicad(19723, lose_beam_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await write.create_beams(c, [beam()], 19723)
        result = await write.create_beams(c, [beam()], 19723, False, preview["confirmation_token"])
        with pytest.raises(ValueError, match="consumed"):
            await write.create_beams(c, [beam()], 19723, False, preview["confirmation_token"])
    assert result["items"][0]["status"] == "unknown"
    assert len(fake.elements) == 1


async def test_journal_failure_prevents_creation(monkeypatch):
    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(write, "_journal", fail)
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(OSError):
            await apply(c, [beam()])
    assert "CreateBeams" not in fake.tapir_calls


async def test_changed_input_requires_new_preview():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await write.create_beams(c, [beam()], 19723)
        with pytest.raises(ValueError, match="changed"):
            await write.create_beams(
                c, [beam(width=0.8)], 19723, False, preview["confirmation_token"]
            )
    assert "CreateBeams" not in fake.tapir_calls
