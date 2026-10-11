"""MoveElements safety tests. Every request is routed through httpx.MockTransport."""

import json
from pathlib import Path

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.connection.errors import AmbiguousTarget
from archicad_mcp_aberto.tools import write
from tests.unit.fake_archicad import BOUNDING_BOXES_FIXTURE, FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
A = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
B = "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"
MISSING = "CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC"
BOX2D = BOUNDING_BOXES_FIXTURE["2d"]["boundingBoxes2D"][0]["boundingBox2D"]
BOX3D = BOUNDING_BOXES_FIXTURE["3d"]["boundingBoxes3D"][0]["boundingBox3D"]


@pytest.fixture(autouse=True)
def receipt_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path / "receipts"))
    return tmp_path / "receipts"


def move(guid=A, x=1.0, y=0.0, z=0.0):
    return {"guid": guid, "vector": {"x": x, "y": y, "z": z}}


def model(**changes):
    return FakeArchicad(19723, elements={A: "Wall", B: "Column"}, **changes)


def client(*instances):
    return ArchicadClient(transport=fake_transport(*instances))


async def apply(c, moves, port=19723):
    preview = await write.move_elements(c, moves, port)
    return await write.move_elements(c, moves, port, False, preview["confirmation_token"])


async def test_preview_reads_boxes_and_changes_nothing(receipt_directory):
    fake = model()
    async with client(fake) as c:
        result = await write.move_elements(c, [move(A.lower(), 2, 1, 0.5)])
    item = result["items"][0]
    assert result["dry_run"] is True and result["operation"] == "move_elements"
    assert item["element_guid"] == A and item["type"] == "Wall"
    assert item["before"] == {"2d": BOX2D, "3d": BOX3D}
    assert item["parameters"] == {
        "elementId": {"guid": A},
        "moveVector": {"x": 2.0, "y": 1.0, "z": 0.5},
        "copy": False,
    }
    assert "MoveElements" not in fake.tapir_calls
    assert not receipt_directory.exists()


async def test_apply_moves_and_verifies_each_box(receipt_directory):
    fake = model()
    async with client(fake) as c:
        result = await apply(c, [move(A, 2, 1, 0.5), move(B, y=-3)])
    assert result["status"] == "verified"
    assert [i["status"] for i in result["items"]] == ["verified", "verified"]
    moved = fake.bounding_boxes_3d[A]["boundingBox3D"]
    assert moved["xMin"] == BOX3D["xMin"] + 2 and moved["zMax"] == BOX3D["zMax"] + 0.5
    assert fake.tapir_calls.count("MoveElements") == 1
    saved = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
    assert saved["status"] == "verified" and all(i["move_receipt_id"] for i in saved["items"])
    assert "Undo" in result["note"]


@pytest.mark.parametrize(
    "bad",
    [
        {"guid": "not-a-guid", "vector": {"x": 1, "y": 0}},
        {"guid": A, "vector": {"x": 0, "y": 0, "z": 0}},
        {"guid": A, "vector": {"x": 0.0005, "y": 0}},
        {"guid": A, "vector": {"x": float("nan"), "y": 0}},
        {"guid": A, "vector": {"x": 20_000, "y": 0}},
        {"guid": A, "vector": {"x": 1, "y": 0}, "copy": True},
    ],
)
async def test_invalid_moves_are_refused_before_any_request(bad):
    fake = model()
    async with client(fake) as c:
        with pytest.raises(ValueError):
            await write.move_elements(c, [bad])
    assert fake.calls == []


async def test_duplicates_and_batch_bounds():
    fake = model()
    async with client(fake) as c:
        with pytest.raises(ValueError, match="only once"):
            await write.move_elements(c, [move(A), move(A.lower(), y=1)])
        with pytest.raises(ValueError, match="between 1 and 50"):
            await write.move_elements(c, [])
    assert fake.calls == []


async def test_unknown_element_is_refused_in_preview():
    fake = model()
    async with client(fake) as c:
        with pytest.raises(ValueError, match=MISSING):
            await write.move_elements(c, [move(A), move(MISSING)])
    assert "MoveElements" not in fake.tapir_calls


async def test_hotlinked_element_is_refused_in_preview():
    fake = model(details={A: {"type": "Wall", "hotlinkId": {"guid": B}}})
    async with client(fake) as c:
        with pytest.raises(ValueError, match="hotlink"):
            await write.move_elements(c, [move(A)])


async def test_element_without_any_box_is_refused():
    error = BOUNDING_BOXES_FIXTURE["error"]
    fake = model(bounding_boxes_2d={A: error}, bounding_boxes_3d={A: error})
    async with client(fake) as c:
        with pytest.raises(ValueError, match="no bounding box"):
            await write.move_elements(c, [move(A)])


async def test_two_dimensional_element_is_checked_on_its_2d_box():
    fake = model(bounding_boxes_3d={A: BOUNDING_BOXES_FIXTURE["error"]})
    async with client(fake) as c:
        result = await apply(c, [move(A, x=-1.5)])
    assert result["items"][0]["before"].keys() == {"2d"}
    assert result["status"] == "verified"


async def test_apply_requires_preview_and_explicit_port():
    fake = model()
    async with client(fake) as c:
        preview = await write.move_elements(c, [move()])
        with pytest.raises(ValueError, match="explicit port"):
            await write.move_elements(c, [move()], None, False, preview["confirmation_token"])
        with pytest.raises(ValueError, match="Preview missing"):
            await write.move_elements(c, [move()], 19723, False, "wrong")
    assert "MoveElements" not in fake.tapir_calls


async def test_element_moved_since_preview_is_refused():
    fake = model()
    async with client(fake) as c:
        preview = await write.move_elements(c, [move()], 19723)
        fake.bounding_boxes_2d[A] = {"boundingBox2D": {**BOX2D, "xMin": BOX2D["xMin"] + 5}}
        with pytest.raises(ValueError, match="changed since preview"):
            await write.move_elements(c, [move()], 19723, False, preview["confirmation_token"])
    assert "MoveElements" not in fake.tapir_calls


async def test_token_is_single_use():
    fake = model()
    async with client(fake) as c:
        preview = await write.move_elements(c, [move()], 19723)
        await write.move_elements(c, [move()], 19723, False, preview["confirmation_token"])
        with pytest.raises(ValueError, match="already consumed"):
            await write.move_elements(c, [move()], 19723, False, preview["confirmation_token"])
    assert fake.tapir_calls.count("MoveElements") == 1


async def test_create_token_cannot_authorize_a_move():
    fake = model()
    wall = {
        "start": {"x": 0, "y": 0},
        "end": {"x": 4, "y": 0},
        "floor_index": 0,
        "height": 3,
        "thickness": 0.2,
    }
    async with client(fake) as c:
        preview = await write.create_walls(c, [wall], 19723)
        with pytest.raises(ValueError, match="changed since preview"):
            await write.move_elements(c, [move()], 19723, False, preview["confirmation_token"])
    assert "MoveElements" not in fake.tapir_calls


async def test_native_failure_is_kept_per_element():
    error = {"success": False, "error": {"code": -1, "message": "Failed to move element"}}
    fake = model(move_errors={1: error})
    async with client(fake) as c:
        result = await apply(c, [move(A), move(B)])
    assert [i["status"] for i in result["items"]] == ["verified", "failed"]
    assert result["items"][1]["error"] == error["error"]
    assert result["status"] == "needs_review"


async def test_reported_success_without_movement_fails_verification():
    fake = model(move_ignored=True)
    async with client(fake) as c:
        result = await apply(c, [move(A, x=3)])
    item = result["items"][0]
    assert item["status"] == "verification_failed"
    assert "2d.xMin" in item["mismatches"] and "3d.xMax" in item["mismatches"]


async def test_lost_response_is_unknown_and_not_retried():
    fake = model(lose_move_response=True)
    async with client(fake) as c:
        result = await apply(c, [move()])
    assert result["items"][0]["status"] == "unknown"
    assert "do not retry" in result["warning"]
    assert fake.tapir_calls.count("MoveElements") == 1


@pytest.mark.parametrize("rows", [[], [{"success": True}, {"success": True}], [{"odd": 1}]])
async def test_unexpected_move_response_is_unknown(monkeypatch, rows):
    fake = model()
    original = fake.handle

    def handle(body):
        response = original(body)
        if (
            body.get("parameters", {}).get("addOnCommandId", {}).get("commandName")
            == "MoveElements"
        ):
            response["result"]["addOnCommandResponse"]["executionResults"] = rows
        return response

    monkeypatch.setattr(fake, "handle", handle)
    async with client(fake) as c:
        result = await apply(c, [move()])
    assert result["items"][0]["status"] == "unknown"


async def test_two_instances_require_explicit_target():
    first, second = model(), FakeArchicad(19724, elements={A: "Wall"})
    async with client(first, second) as c:
        with pytest.raises(AmbiguousTarget):
            await write.move_elements(c, [move()])
    assert "MoveElements" not in first.tapir_calls + second.tapir_calls
