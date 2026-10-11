"""CreateWalls safety tests. Every request is routed through httpx.MockTransport."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.connection.errors import AmbiguousTarget, ArchicadUnavailable
from archicad_mcp_aberto.tools import write
from tests.unit.fake_archicad import CREATE_WALLS_FIXTURE, FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def receipt_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path / "receipts"))
    return tmp_path / "receipts"


def wall(**changes):
    return {
        "start": {"x": 0, "y": 0},
        "end": {"x": 4, "y": 0},
        "height": 3.0,
        "thickness": 0.2,
        "floor_index": 0,
        **changes,
    }


def client(*instances):
    return ArchicadClient(transport=fake_transport(*instances))


async def apply(c, walls, port=19723):
    preview = await write.create_walls(c, walls, port)
    return await write.create_walls(c, walls, port, False, preview["confirmation_token"])


async def test_default_is_read_only_preview(receipt_directory):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        result = await write.create_walls(c, [wall()])
    assert result["dry_run"] is True
    assert result["target"]["port"] == 19723
    assert result["items"][0]["parameters"]["floorIndex"] == 0
    assert result["items"][0]["parameters"]["zCoordinate"] == 0.0
    assert "CreateWalls" not in fake.tapir_calls
    assert fake.elements == {}
    assert not receipt_directory.exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"height": 0},
        {"height": -1},
        {"thickness": 0},
        {"thickness": -0.2},
        {"height": float("nan")},
        {"height": float("inf")},
        {"bottom_offset": float("-inf")},
        {"offset": float("nan")},
        {"start": {"x": float("nan"), "y": 0}},
        {"height": True},
        {"height": "3"},
        {"floor_index": True},
        {"floor_index": 0.5},
        {"floor_index": "0"},
        {"reference_line": "CoreCenter"},
        {"end": {"x": 0, "y": 0}},
        {"unexpected": 123},
        {"start": {"x": 0, "y": 0, "z": 0}},
    ],
)
async def test_invalid_input_is_rejected_before_any_request(changes):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        with pytest.raises(ValueError):
            await write.create_walls(c, [wall(**changes)])
    assert fake.calls == []


@pytest.mark.parametrize("size", [0, 21])
async def test_batch_bounds(size):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        with pytest.raises(ValueError, match="between 1 and 20"):
            await write.create_walls(c, [wall()] * size)
    assert fake.calls == []


async def test_missing_story_prevents_writing():
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        with pytest.raises(ValueError, match="does not exist"):
            await write.create_walls(c, [wall(floor_index=5)])
    assert "CreateWalls" not in fake.tapir_calls


async def test_apply_requires_a_preview_and_explicit_port():
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        with pytest.raises(ValueError, match="explicit port"):
            await write.create_walls(c, [wall()], dry_run=False)
        with pytest.raises(ValueError, match="Preview missing"):
            await write.create_walls(c, [wall()], 19723, False, "invented-token")
    assert "CreateWalls" not in fake.tapir_calls


async def test_apply_verifies_each_wall_and_persists_receipts():
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        result = await apply(c, [wall(), wall(start={"x": 8, "y": 0}, end={"x": 12, "y": 0})])
    assert result["status"] == "verified"
    assert result["counts"]["verified"] == 2
    assert len(fake.elements) == 2
    ids = {item["wall_receipt_id"] for item in result["items"]}
    assert len(ids) == 2
    for index, item in enumerate(result["items"]):
        assert item["index"] == index
        assert item["status"] == "verified"
        assert item["element_guid"] in fake.elements
        assert item["after"]["details"]["height"] == 3.0
    prepared = json.loads(Path(result["prepared_receipt_path"]).read_text(encoding="utf-8"))
    saved = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
    assert prepared["status"] == "outcome_unknown"
    assert saved["status"] == "verified"
    assert saved["items"] == result["items"]
    assert "confirmation_token" not in saved
    assert fake.tapir_calls.count("CreateWalls") == 1
    assert fake.tapir_calls[-1] == "GetDetailsOfElements"
    assert not any("Save" in name for name in fake.calls + fake.tapir_calls)


async def test_payload_and_verification_use_metres_and_explicit_story():
    fake = FakeArchicad(19723, stories=[{"index": 1, "name": "First", "level": 3.0}])
    async with client(fake) as c:
        result = await apply(
            c,
            [
                wall(
                    floor_index=1,
                    bottom_offset=0.15,
                    thickness=0.08,
                    reference_line="Outside",
                    offset=0.03,
                )
            ],
        )
    request = next(r for r in fake.tapir_requests if r["command"] == "CreateWalls")
    data = request["parameters"]["wallsData"][0]
    assert data["floorIndex"] == 1 and data["zCoordinate"] == 0.15
    assert data["thickness"] == 0.08 and data["arcAngle"] == 0.0
    assert data["structureType"] == "Basic" and data["referenceLineLocation"] == "Outside"
    assert result["items"][0]["after"]["details"]["zCoordinate"] == 3.15
    assert result["status"] == "verified"


async def test_native_partial_failure_keeps_error_and_input_order():
    error = deepcopy(CREATE_WALLS_FIXTURE["create_error"])
    fake = FakeArchicad(19723, create_errors={0: error})
    async with client(fake) as c:
        result = await apply(c, [wall(), wall()])
    assert result["status"] == "needs_review"
    assert result["counts"]["failed"] == 1 and result["counts"]["verified"] == 1
    assert result["items"][0]["index"] == 0
    assert result["items"][0]["error"] == error["error"]
    assert result["items"][1]["status"] == "verified"
    assert len(fake.elements) == 1
    assert result["raw_response"]["elements"][0] == error


async def test_all_native_errors_do_not_claim_success():
    error = deepcopy(CREATE_WALLS_FIXTURE["create_error"])
    fake = FakeArchicad(19723, create_errors={0: error})
    async with client(fake) as c:
        result = await apply(c, [wall()])
    assert result["counts"]["failed"] == 1
    assert result["counts"]["verified"] == 0
    assert fake.elements == {}
    assert fake.tapir_calls[-1] == "CreateWalls"


async def test_two_instances_require_explicit_target():
    first, second = FakeArchicad(19723), FakeArchicad(19724)
    async with client(first, second) as c:
        with pytest.raises(AmbiguousTarget):
            await write.create_walls(c, [wall()])
        result = await apply(c, [wall()], 19724)
    assert result["target"]["port"] == 19724
    assert first.elements == {} and len(second.elements) == 1


@pytest.mark.parametrize("change", ["input", "project", "element_set", "story"])
async def test_changed_preview_is_refused(change):
    fake = FakeArchicad(19723)
    data = [wall()]
    async with client(fake) as c:
        preview = await write.create_walls(c, data, 19723)
        if change == "input":
            data[0]["height"] = 4.0
        elif change == "project":
            fake.project_name = "Another project"
        elif change == "element_set":
            fake.elements["11111111-1111-1111-1111-111111111111"] = "Wall"
        else:
            fake.stories[0]["level"] = 1.0
        with pytest.raises(ValueError, match="changed since preview"):
            await write.create_walls(c, data, 19723, False, preview["confirmation_token"])
    assert "CreateWalls" not in fake.tapir_calls


async def test_preview_cannot_be_redirected_to_another_port():
    first, second = FakeArchicad(19723), FakeArchicad(19724)
    async with client(first, second) as c:
        preview = await write.create_walls(c, [wall()], 19723)
        with pytest.raises(ValueError, match="changed since preview"):
            await write.create_walls(c, [wall()], 19724, False, preview["confirmation_token"])
    assert not first.elements and not second.elements


async def test_expired_preview_cannot_be_applied():
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        preview = await write.create_walls(c, [wall()], 19723)
        token = preview["confirmation_token"]
        _, plan = write._states[c].previews[token]
        write._states[c].previews[token] = (0, plan)
        with pytest.raises(ValueError, match="expired"):
            await write.create_walls(c, [wall()], 19723, False, token)
    assert not fake.elements


async def test_preview_is_not_valid_in_a_reopened_client_session():
    fake = FakeArchicad(19723)
    c = client(fake)
    async with c:
        preview = await write.create_walls(c, [wall()], 19723)
    async with c:
        with pytest.raises(ValueError, match="Preview missing"):
            await write.create_walls(c, [wall()], 19723, False, preview["confirmation_token"])
    assert not fake.elements


async def test_parallel_apply_consumes_token_once():
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        preview = await write.create_walls(c, [wall()], 19723)
        outcomes = await asyncio.gather(
            *[
                write.create_walls(c, [wall()], 19723, False, preview["confirmation_token"])
                for _ in range(2)
            ],
            return_exceptions=True,
        )
    assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, ValueError) for outcome in outcomes) == 1
    assert fake.tapir_calls.count("CreateWalls") == 1
    assert len(fake.elements) == 1


async def test_lost_response_does_not_retry_or_claim_failure():
    fake = FakeArchicad(19723, lose_create_response=True)
    async with client(fake) as c:
        preview = await write.create_walls(c, [wall()], 19723)
        token = preview["confirmation_token"]
        result = await write.create_walls(c, [wall()], 19723, False, token)
        with pytest.raises(ValueError, match="consumed"):
            await write.create_walls(c, [wall()], 19723, False, token)
    assert result["items"][0]["status"] == "unknown"
    assert result["counts"]["unknown"] == 1 and len(fake.elements) == 1
    assert fake.tapir_calls.count("CreateWalls") == 1
    assert Path(result["receipt_path"]).exists()


@pytest.mark.parametrize("bad_rows", [[], [{}], [None], [{"elementId": {"guid": "bad"}}]])
async def test_unexpected_creation_response_is_recorded_as_unknown(monkeypatch, bad_rows):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        original = c.tapir

        async def faulty(port, command, parameters=None, **kwargs):
            result = await original(port, command, parameters, **kwargs)
            return {"elements": deepcopy(bad_rows)} if command == "CreateWalls" else result

        monkeypatch.setattr(c, "tapir", faulty)
        result = await apply(c, [wall()])
    assert result["items"][0]["status"] == "unknown"
    assert result["status"] == "needs_review"
    assert len(fake.elements) == 1


async def test_geometry_mismatch_is_reported(monkeypatch):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        original = c.tapir

        async def faulty(port, command, parameters=None, **kwargs):
            result = await original(port, command, parameters, **kwargs)
            if command == "GetDetailsOfElements":
                result["detailsOfElements"][0]["details"]["height"] = 10.0
            return result

        monkeypatch.setattr(c, "tapir", faulty)
        result = await apply(c, [wall()])
    assert result["items"][0]["status"] == "verification_failed"
    assert result["items"][0]["mismatches"] == ["details.height"]
    assert result["counts"]["verification_failed"] == 1


async def test_verification_unavailable_keeps_successful_write_unverified(monkeypatch):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        original = c.tapir

        async def faulty(port, command, parameters=None, **kwargs):
            if command == "GetDetailsOfElements":
                raise ArchicadUnavailable("Injected verification timeout")
            return await original(port, command, parameters, **kwargs)

        monkeypatch.setattr(c, "tapir", faulty)
        result = await apply(c, [wall()])
    assert result["items"][0]["status"] == "unverified"
    assert result["counts"]["unverified"] == 1 and len(fake.elements) == 1
    assert "verification_error" in result


async def test_unwritable_prepared_receipt_prevents_native_write(monkeypatch):
    fake = FakeArchicad(19723)

    def fail(receipt, phase):
        raise OSError("Injected disk failure")

    monkeypatch.setattr(write, "_journal", fail)
    async with client(fake) as c:
        with pytest.raises(OSError, match="disk failure"):
            await apply(c, [wall()])
    assert "CreateWalls" not in fake.tapir_calls and not fake.elements


async def test_final_receipt_failure_returns_result_and_prepared_path(monkeypatch):
    fake = FakeArchicad(19723)
    original = write._journal

    def fail_final(receipt, phase):
        if phase == "result":
            raise OSError("Injected final receipt failure")
        return original(receipt, phase)

    monkeypatch.setattr(write, "_journal", fail_final)
    async with client(fake) as c:
        result = await apply(c, [wall()])
    assert result["status"] == "verified" and len(fake.elements) == 1
    assert "receipt_error" in result
    assert Path(result["prepared_receipt_path"]).exists()


def timing_client(fake, seen):
    inner = fake_transport(fake)

    class Recorder(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            body = json.loads(request.content)
            name = body.get("parameters", {}).get("addOnCommandId", {}).get("commandName")
            seen[name or body["command"]] = request.extensions["timeout"]["read"]
            return await inner.handle_async_request(request)

    return ArchicadClient(transport=Recorder())


@pytest.mark.parametrize(("env", "expected"), [(None, 120.0), ("45", 45.0)])
async def test_writes_wait_longer_than_reads(monkeypatch, env, expected):
    if env is None:
        monkeypatch.delenv("ARCHICAD_MCP_WRITE_TIMEOUT", raising=False)
    else:
        monkeypatch.setenv("ARCHICAD_MCP_WRITE_TIMEOUT", env)
    seen = {}
    async with timing_client(FakeArchicad(19723), seen) as c:
        result = await apply(c, [wall()])
    assert result["status"] == "verified"
    assert result["write_timeout_seconds"] == expected
    assert seen["CreateWalls"] == seen["GetDetailsOfElements"] == expected
    assert seen["GetStories"] == c.timeout


@pytest.mark.parametrize("env", ["0", "-5", "nan", "abc"])
async def test_invalid_write_timeout_keeps_the_preview_unconsumed(monkeypatch, env):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        preview = await write.create_walls(c, [wall()], 19723)
        monkeypatch.setenv("ARCHICAD_MCP_WRITE_TIMEOUT", env)
        with pytest.raises(ValueError):
            await write.create_walls(c, [wall()], 19723, False, preview["confirmation_token"])
        monkeypatch.delenv("ARCHICAD_MCP_WRITE_TIMEOUT")
        result = await write.create_walls(c, [wall()], 19723, False, preview["confirmation_token"])
    assert result["status"] == "verified"
    assert fake.tapir_calls.count("CreateWalls") == 1
