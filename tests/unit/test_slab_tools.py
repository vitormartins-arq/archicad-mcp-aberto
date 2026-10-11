"""CreateSlabs safety tests. Every request is routed through httpx.MockTransport."""

import asyncio
import json
from copy import deepcopy
from pathlib import Path

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.connection.errors import AmbiguousTarget, ArchicadUnavailable
from archicad_mcp_aberto.tools import write
from tests.unit.fake_archicad import CREATE_SLABS_FIXTURE, FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def receipt_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path / "receipts"))
    return tmp_path / "receipts"


def wall(**changes):
    return {
        "outline": [{"x": 0, "y": 0}, {"x": 4, "y": 0}, {"x": 4, "y": 3}, {"x": 0, "y": 3}],
        "thickness": 0.2,
        "floor_index": 0,
        "level": 0.0,
        **changes,
    }


def client(*instances):
    return ArchicadClient(transport=fake_transport(*instances))


async def apply(c, walls, port=19723):
    preview = await write.create_slabs(c, walls, port)
    return await write.create_slabs(c, walls, port, False, preview["confirmation_token"])


async def test_default_is_read_only_preview(receipt_directory):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        result = await write.create_slabs(c, [wall()])
    assert result["dry_run"] is True
    assert result["target"]["port"] == 19723
    assert result["items"][0]["parameters"]["floorIndex"] == 0
    assert result["items"][0]["parameters"]["level"] == 0.0
    assert "CreateSlabs" not in fake.tapir_calls
    assert fake.elements == {}
    assert not receipt_directory.exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"thickness": 0},
        {"thickness": -1},
        {"thickness": True},
        {"thickness": "0.2"},
        {"thickness": float("nan")},
        {"level": float("inf")},
        {"level": True},
        {"floor_index": True},
        {"floor_index": 0.5},
        {"floor_index": "0"},
        {"holes": []},
        {"polygon_arcs": []},
        {"outline": [{"x": 0, "y": 0}] * 3},
        {"outline": [{"x": 0, "y": 0}, {"x": 1, "y": 1}, {"x": 2, "y": 2}]},
        {"outline": [{"x": 0, "y": 0}, {"x": 3, "y": 3}, {"x": 0, "y": 2}, {"x": 2, "y": 0}]},
        {"outline": [{"x": float("nan"), "y": 0}, {"x": 4, "y": 0}, {"x": 0, "y": 3}]},
    ],
)
async def test_invalid_input_is_rejected_before_any_request(changes):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        with pytest.raises(ValueError):
            await write.create_slabs(c, [wall(**changes)])
    assert fake.calls == []


@pytest.mark.parametrize("size", [0, 21])
async def test_batch_bounds(size):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        with pytest.raises(ValueError, match="between 1 and 20"):
            await write.create_slabs(c, [wall()] * size)
    assert fake.calls == []


async def test_missing_story_prevents_writing():
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        with pytest.raises(ValueError, match="does not exist"):
            await write.create_slabs(c, [wall(floor_index=5)])
    assert "CreateSlabs" not in fake.tapir_calls


async def test_apply_requires_a_preview_and_explicit_port():
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        with pytest.raises(ValueError, match="explicit port"):
            await write.create_slabs(c, [wall()], dry_run=False)
        with pytest.raises(ValueError, match="Preview missing"):
            await write.create_slabs(c, [wall()], 19723, False, "invented-token")
    assert "CreateSlabs" not in fake.tapir_calls


async def test_apply_verifies_each_wall_and_persists_receipts():
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        result = await apply(c, [wall(), wall(level=0.5)])
    assert result["status"] == "verified"
    assert result["counts"]["verified"] == 2
    assert len(fake.elements) == 2
    ids = {item["slab_receipt_id"] for item in result["items"]}
    assert len(ids) == 2
    for index, item in enumerate(result["items"]):
        assert item["index"] == index
        assert item["status"] == "verified"
        assert item["element_guid"] in fake.elements
        assert item["after"]["details"]["thickness"] == 0.2
    prepared = json.loads(Path(result["prepared_receipt_path"]).read_text(encoding="utf-8"))
    saved = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
    assert prepared["status"] == "outcome_unknown"
    assert saved["status"] == "verified"
    assert saved["items"] == result["items"]
    assert "confirmation_token" not in saved
    assert fake.tapir_calls.count("CreateSlabs") == 1
    assert fake.tapir_calls[-1] == "GetDetailsOfElements"
    assert not any("Save" in name for name in fake.calls + fake.tapir_calls)


async def test_payload_and_verification_use_metres_and_explicit_story():
    fake = FakeArchicad(19723, stories=[{"index": 1, "name": "First", "level": 3.0}])
    async with client(fake) as c:
        result = await apply(c, [wall(floor_index=1, level=3.15, thickness=0.08)])
    request = next(r for r in fake.tapir_requests if r["command"] == "CreateSlabs")
    data = request["parameters"]["slabsData"][0]
    assert data["floorIndex"] == 1 and data["level"] == 3.15
    assert data["thickness"] == 0.08 and data["holes"] == []
    assert data["referencePlaneLocation"] == "Top"
    after = result["items"][0]["after"]["details"]
    assert after["zCoordinate"] == 3.15 and after["level"] == pytest.approx(0.15)
    assert result["status"] == "verified"


async def test_native_partial_failure_keeps_error_and_input_order():
    error = deepcopy(CREATE_SLABS_FIXTURE["create_error"])
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
    error = deepcopy(CREATE_SLABS_FIXTURE["create_error"])
    fake = FakeArchicad(19723, create_errors={0: error})
    async with client(fake) as c:
        result = await apply(c, [wall()])
    assert result["counts"]["failed"] == 1
    assert result["counts"]["verified"] == 0
    assert fake.elements == {}
    assert fake.tapir_calls[-1] == "CreateSlabs"


async def test_two_instances_require_explicit_target():
    first, second = FakeArchicad(19723), FakeArchicad(19724)
    async with client(first, second) as c:
        with pytest.raises(AmbiguousTarget):
            await write.create_slabs(c, [wall()])
        result = await apply(c, [wall()], 19724)
    assert result["target"]["port"] == 19724
    assert first.elements == {} and len(second.elements) == 1


@pytest.mark.parametrize("change", ["input", "project", "element_set", "story"])
async def test_changed_preview_is_refused(change):
    fake = FakeArchicad(19723)
    data = [wall()]
    async with client(fake) as c:
        preview = await write.create_slabs(c, data, 19723)
        if change == "input":
            data[0]["thickness"] = 0.4
        elif change == "project":
            fake.project_name = "Another project"
        elif change == "element_set":
            fake.elements["11111111-1111-1111-1111-111111111111"] = "Slab"
        else:
            fake.stories[0]["level"] = 1.0
        with pytest.raises(ValueError, match="changed since preview"):
            await write.create_slabs(c, data, 19723, False, preview["confirmation_token"])
    assert "CreateSlabs" not in fake.tapir_calls


async def test_preview_cannot_be_redirected_to_another_port():
    first, second = FakeArchicad(19723), FakeArchicad(19724)
    async with client(first, second) as c:
        preview = await write.create_slabs(c, [wall()], 19723)
        with pytest.raises(ValueError, match="changed since preview"):
            await write.create_slabs(c, [wall()], 19724, False, preview["confirmation_token"])
    assert not first.elements and not second.elements


async def test_expired_preview_cannot_be_applied():
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        preview = await write.create_slabs(c, [wall()], 19723)
        token = preview["confirmation_token"]
        _, plan = write._states[c].previews[token]
        write._states[c].previews[token] = (0, plan)
        with pytest.raises(ValueError, match="expired"):
            await write.create_slabs(c, [wall()], 19723, False, token)
    assert not fake.elements


async def test_preview_is_not_valid_in_a_reopened_client_session():
    fake = FakeArchicad(19723)
    c = client(fake)
    async with c:
        preview = await write.create_slabs(c, [wall()], 19723)
    async with c:
        with pytest.raises(ValueError, match="Preview missing"):
            await write.create_slabs(c, [wall()], 19723, False, preview["confirmation_token"])
    assert not fake.elements


async def test_parallel_apply_consumes_token_once():
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        preview = await write.create_slabs(c, [wall()], 19723)
        outcomes = await asyncio.gather(
            *[
                write.create_slabs(c, [wall()], 19723, False, preview["confirmation_token"])
                for _ in range(2)
            ],
            return_exceptions=True,
        )
    assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
    assert sum(isinstance(outcome, ValueError) for outcome in outcomes) == 1
    assert fake.tapir_calls.count("CreateSlabs") == 1
    assert len(fake.elements) == 1


async def test_lost_response_does_not_retry_or_claim_failure():
    fake = FakeArchicad(19723, lose_slab_response=True)
    async with client(fake) as c:
        preview = await write.create_slabs(c, [wall()], 19723)
        token = preview["confirmation_token"]
        result = await write.create_slabs(c, [wall()], 19723, False, token)
        with pytest.raises(ValueError, match="consumed"):
            await write.create_slabs(c, [wall()], 19723, False, token)
    assert result["items"][0]["status"] == "unknown"
    assert result["counts"]["unknown"] == 1 and len(fake.elements) == 1
    assert fake.tapir_calls.count("CreateSlabs") == 1
    assert Path(result["receipt_path"]).exists()


@pytest.mark.parametrize("bad_rows", [[], [{}], [None], [{"elementId": {"guid": "bad"}}]])
async def test_unexpected_creation_response_is_recorded_as_unknown(monkeypatch, bad_rows):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        original = c.tapir

        async def faulty(port, command, parameters=None, **kwargs):
            result = await original(port, command, parameters, **kwargs)
            return {"elements": deepcopy(bad_rows)} if command == "CreateSlabs" else result

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
                result["detailsOfElements"][0]["details"]["thickness"] = 10.0
            return result

        monkeypatch.setattr(c, "tapir", faulty)
        result = await apply(c, [wall()])
    assert result["items"][0]["status"] == "verification_failed"
    assert result["items"][0]["mismatches"] == ["details.thickness"]
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
    assert "CreateSlabs" not in fake.tapir_calls and not fake.elements


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


async def test_fixture_provenance_and_documented_request():
    assert CREATE_SLABS_FIXTURE["provenance"]["live_capture"] is False
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        await apply(c, [wall()])
    request = next(r for r in fake.tapir_requests if r["command"] == "CreateSlabs")
    assert request["parameters"] == CREATE_SLABS_FIXTURE["create_request"]


async def test_wall_token_cannot_authorize_slabs():
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        preview = await write.create_walls(
            c,
            [
                {
                    "start": {"x": 0, "y": 0},
                    "end": {"x": 4, "y": 0},
                    "height": 3,
                    "thickness": 0.2,
                    "floor_index": 0,
                }
            ],
            19723,
        )
        with pytest.raises(ValueError, match="changed since preview"):
            await write.create_slabs(c, [wall()], 19723, False, preview["confirmation_token"])
    assert not fake.elements


@pytest.mark.parametrize(
    "field", ["polygonOutline", "holes", "polygonArcs", "level", "zCoordinate"]
)
async def test_slab_verification_checks_geometry_and_levels(monkeypatch, field):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        original = c.tapir

        async def faulty(port, command, parameters=None, **kwargs):
            result = await original(port, command, parameters, **kwargs)
            if command == "GetDetailsOfElements":
                details = result["detailsOfElements"][0]["details"]
                details[field] = (
                    [{"unexpected": True}]
                    if field in {"holes", "polygonArcs", "polygonOutline"}
                    else 10
                )
            return result

        monkeypatch.setattr(c, "tapir", faulty)
        result = await apply(c, [wall()])
    assert result["items"][0]["status"] == "verification_failed"
    assert f"details.{field}" in result["items"][0]["mismatches"]


async def test_closed_clockwise_concave_outline():
    points = [{"x": 0, "y": 0}, {"x": 0, "y": 3}, {"x": 2, "y": 1}, {"x": 4, "y": 0}]
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        result = await apply(c, [wall(outline=points + [points[0]])])
    assert result["status"] == "verified"
    assert result["items"][0]["parameters"]["polygonCoordinates"] == points


async def test_slab_server_registration():
    from archicad_mcp_aberto.server import create_server

    tools = await create_server(lambda: client(FakeArchicad(19723))).list_tools()
    tool = next(t for t in tools if t.name == "create_slabs")
    assert tool.inputSchema["properties"]["dry_run"]["default"] is True
    assert not tool.annotations.readOnlyHint and not tool.annotations.idempotentHint


async def test_adjacent_backtracking_edges_rejected():
    fake = FakeArchicad(19723)
    points = [
        {"x": 0, "y": 0},
        {"x": 4, "y": 0},
        {"x": 2, "y": 0},
        {"x": 2, "y": 3},
        {"x": 0, "y": 3},
    ]
    async with client(fake) as c:
        with pytest.raises(ValueError, match="overlap"):
            await write.create_slabs(c, [wall(outline=points)])
    assert fake.calls == []


async def test_verification_accepts_rotated_reversed_outline(monkeypatch):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        original = c.tapir

        async def rotated(port, command, parameters=None, **kwargs):
            result = await original(port, command, parameters, **kwargs)
            if command == "GetDetailsOfElements":
                details = result["detailsOfElements"][0]["details"]
                points = list(reversed(details["polygonOutline"][:-1]))
                points = points[1:] + points[:1]
                details["polygonOutline"] = points + [points[0]]
            return result

        monkeypatch.setattr(c, "tapir", rotated)
        assert (await apply(c, [wall()]))["status"] == "verified"
