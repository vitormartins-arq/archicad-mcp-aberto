"""Box morph creation, only with MockTransport."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import morphs
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
STORIES = [{"index": 0, "name": "Ground", "level": 0}, {"index": 1, "name": "Upper", "level": 3}]
INPUT = {
    "base_point": {"x": 1, "y": 2, "z": 3.5},
    "size_x": 0.6,
    "size_y": 0.4,
    "size_z": 0.9,
    "floor_index": 1,
}


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    return FakeArchicad(19723, stories=deepcopy(STORIES), **kwargs)


async def apply(c, entries):
    preview = await morphs.create_morphs(c, entries, 19723)
    return await morphs.create_morphs(c, entries, 19723, False, preview["confirmation_token"])


async def test_preview_then_create_and_verify_story_origin_and_box():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await morphs.create_morphs(c, [INPUT], 19723)
        item = preview["items"][0]
        assert item["parameters"] == {
            "basePoint": {"x": 1, "y": 2, "z": 3.5},
            "size": {"x": 0.6, "y": 0.4, "z": 0.9},
            "floorIndex": 1,
        }
        assert item["expected_box"]["zMax"] == pytest.approx(4.4)
        assert "CreateMorphs" not in fake.tapir_calls and fake.elements == {}
        result = await morphs.create_morphs(c, [INPUT], 19723, False, preview["confirmation_token"])
        with pytest.raises(ValueError, match="consumed"):
            await morphs.create_morphs(c, [INPUT], 19723, False, preview["confirmation_token"])
    assert result["status"] == "verified"
    item = result["items"][0]
    assert item["morph_receipt_id"] and item["after"]["type"] == "Morph"
    assert item["after_box"]["xMax"] == pytest.approx(1.6)
    payload = next(r["parameters"] for r in fake.tapir_requests if r["command"] == "CreateMorphs")
    assert list(payload) == ["morphsData"]
    assert not any("Save" in cmd or "Delete" in cmd for cmd in fake.tapir_calls)


async def test_box_out_of_place_fails_verification():
    fake = model(morph_box_shift=0.05)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [INPUT])
    item = result["items"][0]
    assert item["status"] == "verification_failed"
    assert item["mismatches"] == ["boundingBox3D"]


async def test_wrong_story_or_rotated_axes_in_read_back_are_mismatches():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [INPUT])
    item = result["items"][0]
    row = deepcopy(fake.details[item["element_guid"]])
    assert morphs._mismatches(item, row) == []
    row["floorIndex"] = 0
    row["details"]["xAxis"] = {"x": 0.0, "y": 1.0, "z": 0.0}
    assert morphs._mismatches(item, row) == ["floorIndex", "details.xAxis"]


async def test_per_item_error_keeps_the_others():
    fake = model(create_errors={0: {"error": {"code": -1, "message": "Failed to create morph."}}})
    second = {**INPUT, "base_point": {"x": 5, "y": 5, "z": 3}}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [INPUT, second])
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]


async def test_unknown_story_and_bad_sizes_are_refused_before_writing():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="story 7"):
            await morphs.create_morphs(c, [{**INPUT, "floor_index": 7}], 19723)
        with pytest.raises(ValidationError):
            await morphs.create_morphs(c, [{**INPUT, "size_z": 0}], 19723)
        with pytest.raises(ValidationError):
            await morphs.create_morphs(c, [{**INPUT, "base_point": {"x": "nan", "y": 0, "z": 0}}])
        with pytest.raises(ValueError, match="between 1 and 50"):
            await morphs.create_morphs(c, [INPUT] * 51, 19723)
    assert "CreateMorphs" not in fake.tapir_calls
