"""CreateObjects safety tests. Every request is routed through httpx.MockTransport."""

import json
import math
from pathlib import Path

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.connection.errors import AmbiguousTarget
from archicad_mcp_aberto.server import create_server
from archicad_mcp_aberto.tools import write
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
TABLE = "Mesa Retangular 30"


@pytest.fixture(autouse=True)
def receipt_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path / "receipts"))
    return tmp_path / "receipts"


def obj(**changes):
    return {
        "library_part_name": TABLE,
        "origin": {"x": 2.0, "y": 1.5},
        "floor_index": 0,
        "base_level": 0.0,
        **changes,
    }


def client(*instances):
    return ArchicadClient(transport=fake_transport(*instances))


async def apply(c, objects, port=19723):
    preview = await write.create_objects(c, objects, port)
    return await write.create_objects(c, objects, port, False, preview["confirmation_token"])


async def test_default_is_read_only_preview(receipt_directory):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        result = await write.create_objects(c, [obj(angle=0.5)])
    assert result["dry_run"] is True and result["operation"] == "create_objects"
    assert result["items"][0]["parameters"] == {
        "libraryPartName": TABLE,
        "coordinates": {"x": 2.0, "y": 1.5, "z": 0.0},
        "floorIndex": 0,
        "angle": 0.5,
    }
    assert "library part" in result["note"]
    assert "CreateObjects" not in fake.tapir_calls
    assert fake.elements == {}
    assert not receipt_directory.exists()


async def test_apply_creates_and_verifies(receipt_directory):
    stories = [
        {"index": 0, "name": "Térreo", "level": 0.0},
        {"index": 1, "name": "Superior", "level": 3.0},
    ]
    fake = FakeArchicad(19723, stories=stories)
    async with client(fake) as c:
        result = await apply(c, [obj(), obj(floor_index=1, base_level=3.4, angle=math.pi / 2)])
    assert result["status"] == "verified"
    assert result["counts"]["verified"] == 2
    request = next(r for r in fake.tapir_requests if r["command"] == "CreateObjects")
    assert request["parameters"]["objectsData"][1] == {
        "libraryPartName": TABLE,
        "coordinates": {"x": 2.0, "y": 1.5, "z": 3.4},
        "floorIndex": 1,
        "angle": math.pi / 2,
    }
    assert all(item["object_receipt_id"] for item in result["items"])
    assert sorted(fake.elements.values()) == ["Object", "Object"]
    assert "Save" not in " ".join(fake.calls + fake.tapir_calls)
    saved = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
    assert saved["status"] == "verified"


async def test_negative_angle_matches_stored_turn():
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        result = await apply(c, [obj(angle=-math.pi / 4)])
    assert result["items"][0]["status"] == "verified"
    stored = fake.details[result["items"][0]["element_guid"]]["details"]["angle"]
    assert stored == pytest.approx(7 * math.pi / 4)


async def test_library_name_match_ignores_case():
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        result = await apply(c, [obj(library_part_name=TABLE.upper())])
    assert result["items"][0]["status"] == "verified"


async def test_unknown_library_part_refused_in_dry_run():
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        with pytest.raises(ValueError, match="name not in loaded"):
            await write.create_objects(c, [obj(), obj(library_part_name="Não Existe")], 19723)
    assert "CreateObjects" not in fake.tapir_calls
    assert not fake.elements


async def test_native_failure_still_isolated_per_item():
    fake = FakeArchicad(19723, create_errors={1: {"error": {"code": -1, "message": "Refused"}}})
    async with client(fake) as c:
        result = await apply(c, [obj(), obj(angle=0.5), obj(angle=1.0)])
    assert [item["status"] for item in result["items"]] == ["verified", "failed", "verified"]
    assert result["status"] == "needs_review"


@pytest.mark.parametrize(
    "changes",
    [
        {"library_part_name": ""},
        {"library_part_name": " Mesa"},
        {"library_part_name": "Mesa "},
        {"library_part_name": "x" * 256},
        {"library_part_name": 3},
        {"angle": float("nan")},
        {"angle": float("inf")},
        {"angle": "0"},
        {"base_level": float("-inf")},
        {"base_level": True},
        {"floor_index": 0.5},
        {"floor_index": "0"},
        {"origin": {"x": 0, "y": 0, "z": 0}},
        {"origin": {"x": float("nan"), "y": 0}},
        {"dimensions": {"x": 1, "y": 1, "z": 1}},
        {"unexpected": 1},
    ],
)
async def test_invalid_inputs_fail_before_requests(changes):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        with pytest.raises(ValueError):
            await write.create_objects(c, [obj(**changes)])
    assert fake.calls == []


@pytest.mark.parametrize("count", [0, 21])
async def test_batch_bounds(count):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        with pytest.raises(ValueError, match="between 1 and 20"):
            await write.create_objects(c, [obj()] * count)
    assert fake.calls == []


async def test_accepts_twenty():
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        result = await write.create_objects(c, [obj(origin={"x": i, "y": 0}) for i in range(20)])
    assert len(result["items"]) == 20


async def test_missing_story_refused_before_create():
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        with pytest.raises(ValueError, match="story 4 does not exist"):
            await write.create_objects(c, [obj(floor_index=4)])
    assert "CreateObjects" not in fake.tapir_calls


async def test_apply_requires_port_and_valid_single_use_token():
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        preview = await write.create_objects(c, [obj()], 19723)
        token = preview["confirmation_token"]
        with pytest.raises(ValueError, match="explicit port"):
            await write.create_objects(c, [obj()], None, False, token)
        with pytest.raises(ValueError, match="Preview missing"):
            await write.create_objects(c, [obj()], 19723, False, "nope")
        await write.create_objects(c, [obj()], 19723, False, token)
        with pytest.raises(ValueError, match="Preview missing"):
            await write.create_objects(c, [obj()], 19723, False, token)
    assert fake.tapir_calls.count("CreateObjects") == 1


async def test_changed_inputs_need_new_preview():
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        preview = await write.create_objects(c, [obj()], 19723)
        with pytest.raises(ValueError, match="changed since preview"):
            await write.create_objects(
                c, [obj(angle=0.1)], 19723, False, preview["confirmation_token"]
            )
    assert "CreateObjects" not in fake.tapir_calls


async def test_column_token_cannot_authorize_objects():
    fake = FakeArchicad(19723)
    column = {
        "origin": {"x": 2.0, "y": 1.5},
        "floor_index": 0,
        "height": 3.0,
        "base_level": 0.0,
        "width": 0.3,
        "depth": 0.3,
    }
    async with client(fake) as c:
        preview = await write.create_columns(c, [column], 19723)
        with pytest.raises(ValueError, match="changed since preview"):
            await write.create_objects(c, [obj()], 19723, False, preview["confirmation_token"])
    assert "CreateObjects" not in fake.tapir_calls


async def test_lost_response_is_unknown_and_not_retried():
    fake = FakeArchicad(19723, lose_object_response=True)
    async with client(fake) as c:
        result = await apply(c, [obj()])
    assert result["items"][0]["status"] == "unknown"
    assert "do not retry" in result["warning"]
    assert fake.tapir_calls.count("CreateObjects") == 1


async def test_wrong_stored_position_is_verification_failed():
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        original = fake._tapir

        def shifted(params):
            response = original(params)
            if params["addOnCommandId"]["commandName"] == "CreateObjects":
                for row in fake.details.values():
                    if row["type"] == "Object":
                        row["details"]["origin"]["x"] += 0.01
                        row["details"]["libPart"]["name"] = "Outra"
            return response

        fake._tapir = shifted
        result = await apply(c, [obj()])
    item = result["items"][0]
    assert item["status"] == "verification_failed"
    assert item["mismatches"] == ["details.origin.x", "details.libPart.name"]


async def test_ambiguous_target_refused():
    first, second = FakeArchicad(19723), FakeArchicad(19724)
    async with client(first, second) as c:
        with pytest.raises(AmbiguousTarget):
            await write.create_objects(c, [obj()])
    assert first.tapir_calls == second.tapir_calls == []


async def test_registration_is_a_write_tool():
    tool = next(t for t in await create_server().list_tools() if t.name == "create_objects")
    assert not tool.annotations.readOnlyHint and tool.annotations.destructiveHint
    assert tool.inputSchema["properties"]["dry_run"]["default"] is True
