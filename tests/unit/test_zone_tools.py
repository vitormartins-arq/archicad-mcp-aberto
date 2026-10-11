from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import write
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
OUTLINE = [{"x": 0, "y": 0}, {"x": 4, "y": 0}, {"x": 4, "y": 3}, {"x": 0, "y": 3}]


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def zone(**changes):
    return {
        "outline": deepcopy(OUTLINE),
        "name": "Office",
        "number": "001",
        "floor_index": 0,
        **changes,
    }


async def apply(c, zones):
    preview = await write.create_zones(c, zones, 19723)
    return await write.create_zones(c, zones, 19723, False, preview["confirmation_token"])


async def test_preview_apply_and_closed_polygon_normalization():
    fake = FakeArchicad(19723)
    inputs = [zone(outline=OUTLINE + [OUTLINE[0]])]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await write.create_zones(c, inputs, 19723)
        assert "CreateZones" not in fake.tapir_calls
        assert len(preview["items"][0]["parameters"]["geometry"]["polygonCoordinates"]) == 4
        result = await write.create_zones(c, inputs, 19723, False, preview["confirmation_token"])
        with pytest.raises(ValueError, match="consumed"):
            await write.create_zones(c, inputs, 19723, False, preview["confirmation_token"])
    assert result["status"] == "verified"
    assert result["items"][0]["zone_receipt_id"]
    assert result["receipt_path"]


@pytest.mark.parametrize(
    "outline",
    [
        [{"x": 0, "y": 0}, {"x": 1, "y": 0}],
        [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 2, "y": 0}],
        [{"x": 0, "y": 0}, {"x": 2, "y": 2}, {"x": 0, "y": 2}, {"x": 2, "y": 0}],
        OUTLINE + [OUTLINE[1]],
    ],
)
async def test_same_polygon_validation_as_slabs(outline):
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await write.create_zones(c, [zone(outline=outline)])
    with pytest.raises(ValueError):
        write.SlabCreate(outline=outline, floor_index=0, thickness=0.2, level=0.0)
    assert not fake.calls


@pytest.mark.parametrize(
    "changes",
    [{"name": ""}, {"number": " "}, {"number": 1}, {"floor_index": True}, {"unexpected": 1}],
)
async def test_invalid_metadata_before_network(changes):
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await write.create_zones(c, [zone(**changes)])
    assert not fake.calls


@pytest.mark.parametrize("count", [0, 21])
async def test_batch_limits(count):
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as c:
        with pytest.raises(ValueError, match="1 and 20"):
            await write.create_zones(c, [zone()] * count)


async def test_missing_story_refused():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="does not exist"):
            await write.create_zones(c, [zone(floor_index=9)])
    assert "CreateZones" not in fake.tapir_calls


async def test_concave_simple_polygon():
    points = [{"x": 0, "y": 0}, {"x": 4, "y": 0}, {"x": 2, "y": 1}, {"x": 0, "y": 3}]
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as c:
        assert (await apply(c, [zone(outline=points)]))["status"] == "verified"


async def test_partial_native_error():
    fake = FakeArchicad(19723, create_errors={1: {"error": {"code": -1, "message": "Refused"}}})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [zone(), zone(number="002")])
    assert [i["status"] for i in result["items"]] == ["verified", "failed"]
    assert len({i["zone_receipt_id"] for i in result["items"]}) == 2


@pytest.mark.parametrize(
    "key,value",
    [
        ("name", "Changed"),
        ("numberStr", "9"),
        ("isManual", False),
        ("holes", [{}]),
        ("polygonOutline", [{"x": 50, "y": 50}]),
    ],
)
async def test_changed_details_not_verified(monkeypatch, key, value):
    original = FakeArchicad._tapir

    def altered(self, params):
        result = original(self, params)
        if params["addOnCommandId"]["commandName"] == "CreateZones":
            for row in self.details.values():
                row["details"][key] = deepcopy(value)
        return result

    monkeypatch.setattr(FakeArchicad, "_tapir", altered)
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as c:
        result = await apply(c, [zone()])
    assert result["items"][0]["status"] == "verification_failed"


async def test_contour_rotation_and_reversal_are_equivalent(monkeypatch):
    original = FakeArchicad._tapir

    def reordered(self, params):
        result = original(self, params)
        if params["addOnCommandId"]["commandName"] == "CreateZones":
            for row in self.details.values():
                points = list(reversed(row["details"]["polygonOutline"][:-1]))
                points = points[2:] + points[:2]
                row["details"]["polygonOutline"] = points + [deepcopy(points[0])]
        return result

    monkeypatch.setattr(FakeArchicad, "_tapir", reordered)
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as c:
        assert (await apply(c, [zone()]))["status"] == "verified"


async def test_lost_response_unknown_never_retryable():
    fake = FakeArchicad(19723, lose_zone_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await write.create_zones(c, [zone()], 19723)
        result = await write.create_zones(c, [zone()], 19723, False, preview["confirmation_token"])
        with pytest.raises(ValueError, match="consumed"):
            await write.create_zones(c, [zone()], 19723, False, preview["confirmation_token"])
    assert result["items"][0]["status"] == "unknown"
    assert len(fake.elements) == 1


async def test_journal_failure_prevents_dispatch(monkeypatch):
    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(write, "_journal", fail)
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(OSError):
            await apply(c, [zone()])
    assert "CreateZones" not in fake.tapir_calls


async def test_missing_polygon_arcs_key_is_verified():
    # Tapir 1.7.0 omits polygonArcs for an outline without arcs (CommandBase.cpp,
    # AddPolygonWithHolesFromMemoCoords); the fake must not add it either.
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [zone()])
    row = fake.details[result["items"][0]["element_guid"]]
    assert "polygonArcs" not in row["details"]
    assert result["items"][0]["status"] == "verified"


async def test_unexpected_polygon_arcs_fail_verification():
    fake = FakeArchicad(19723)
    original = fake._tapir

    def with_arc(params):
        response = original(params)
        if params["addOnCommandId"]["commandName"] == "CreateZones":
            for row in fake.details.values():
                if row["type"] == "Zone":
                    row["details"]["polygonArcs"] = [{"begIndex": 0, "endIndex": 1, "arcAngle": 1}]
        return response

    fake._tapir = with_arc
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [zone()])
    assert result["items"][0]["status"] == "verification_failed"
    assert result["items"][0]["mismatches"] == ["details.polygonArcs"]
