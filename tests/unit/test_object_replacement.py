"""New companion-command contract stubs, derived from ObjectReplacementCommands.cpp.

These responses are NOT live captures. Native Undo/parameter execution requires live tests.
"""

import math
from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import object_replacement as tool
from archicad_mcp_aberto.tools import write
from tests.unit.fake_archicad import FakeArchicad, fake_transport

GUID = "ABAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
UNID = "{11111111-1111-4111-8111-111111111111}-{22222222-2222-4222-8222-222222222222}"


@pytest.fixture
def native(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))
    target = {
        "index": 7,
        "unid": UNID,
        "name": "New sign",
        "a": 2.0,
        "b": 0.1,
        "height": 0.5,
        "parameters": {"items": []},
    }
    before = {
        "guid": GUID,
        "stamp": "9007199254740993",
        "library": {**target, "unid": "OLD"},
        "floorIndex": 1,
        "layerIndex": 7,
        "x": 4.0,
        "y": -2.0,
        "level": 1.55,
        "angle": 0.7,
        "reflected": False,
        "a": 0.45,
        "b": 0.016,
        "height": 0.105,
        "xRatio": 1.5,
        "yRatio": 0.8,
        "useXYFixSize": False,
        "fixPoint": 0,
        "offsetX": 0.1,
        "offsetY": -0.2,
        "parameters": {"items": [{"name": "custom", "value": 3.0}]},
        "groupGuid": "GROUP",
        "groupReadCode": 0,
        "classifications": [{"system": "SYSTEM", "item": "ITEM"}],
    }
    state = {
        "sessionId": "boot1",
        "target": target,
        "objects": [before],
        "writes": [],
        "fail": False,
        "drift": False,
        "reads": [],
    }

    async def editable(client, guids, port):
        resolved, context, _ = await write._context(client, port)
        return resolved, context, []

    async def addon(client, port, command, parameters=None, timeout=None):
        if command == "GetObjectReplacementData":
            state["reads"].append(deepcopy(parameters))
            if not parameters["guids"]:
                return deepcopy(
                    {"sessionId": state["sessionId"], "target": state["target"], "objects": []}
                )
            return deepcopy({k: state[k] for k in ("sessionId", "target", "objects")})
        assert command == "ReplaceObjectLibraries"
        state["writes"].append(deepcopy(parameters))
        row = parameters["objects"][0]
        state["objects"][0].update({k: v for k, v in row.items() if k not in ("guid", "stamp")})
        state["objects"][0]["library"] = deepcopy(state["target"])
        state["objects"][0]["stamp"] = "9007199254740994"
        state["objects"][0].update(fixPoint=-1, offsetX=0.0, offsetY=0.0)
        if state["drift"]:
            state["objects"][0]["x"] += 0.1
        if state["fail"]:
            raise ArchicadError("Response lost after mutation")
        return {"objects": deepcopy(state["objects"])}

    monkeypatch.setattr(tool.edit, "_editable", editable)
    monkeypatch.setattr(tool.grids, "_addon", addon)
    return state


def request(**kwargs):
    return {
        "guid": GUID,
        "target_unid": UNID,
        "source_mount": {"x": 0.225, "y": 0.008, "z": 0.0525},
        "target_mount": {"x": -0.3, "y": 0.01, "z": -0.1},
        **kwargs,
    }


@pytest.mark.anyio
@pytest.mark.parametrize("angle,reflected", [(0.0, False), (math.pi / 2, False), (0.7, True)])
async def test_explicit_reference_preserved(native, angle, reflected):
    native["objects"][0].update(angle=angle, reflected=reflected)
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as client:
        preview = await tool.replace_object_libraries(client, [request()], 19723)
        assert native["writes"] == []
        result = await tool.replace_object_libraries(
            client, [request()], 19723, False, preview["confirmation_token"]
        )
        assert result["status"] == "verified"
        item = result["items"][0]
        # Independent explicit rigid transform, not the planner's verification helper.
        point = request()["target_mount"]
        x = -point["x"] if reflected else point["x"]
        actual = (
            item["after"]["x"] + math.cos(angle) * x - math.sin(angle) * point["y"],
            item["after"]["y"] + math.sin(angle) * x + math.cos(angle) * point["y"],
            item["after"]["level"] + point["z"],
        )
        assert actual == pytest.approx(tuple(item["mount_story_coordinates"].values()))
        assert item["after"]["floorIndex"] == 1
        assert item["after"]["a"] == 0.45
        assert item["after"]["b"] == 0.016
        assert len(native["writes"]) == 1
        with pytest.raises(ValueError, match="consumed"):
            await tool.replace_object_libraries(
                client, [request()], 19723, False, preview["confirmation_token"]
            )


@pytest.mark.anyio
@pytest.mark.parametrize("change", ["stamp", "session", "target", "parameters", "project"])
async def test_stale_preview_rejected(native, change):
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        preview = await tool.replace_object_libraries(client, [request()], 19723)
        if change == "stamp":
            native["objects"][0]["stamp"] = "NEW"
        elif change == "session":
            native["sessionId"] = "boot2"
        elif change == "target":
            native["target"]["index"] = 8
        elif change == "parameters":
            native["objects"][0]["parameters"]["items"][0]["value"] = 4.0
        else:
            # A changed story/target context also invalidates the single-use preview.
            fake.stories[0]["level"] += 1.0
        with pytest.raises(ValueError, match="changed since preview"):
            await tool.replace_object_libraries(
                client, [request()], 19723, False, preview["confirmation_token"]
            )
        assert not native["writes"]


@pytest.mark.anyio
async def test_lost_reply_is_unknown_and_read_only_inspection_recovers_state(native):
    native["fail"] = True
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as client:
        preview = await tool.replace_object_libraries(client, [request()], 19723)
        result = await tool.replace_object_libraries(
            client, [request()], 19723, False, preview["confirmation_token"]
        )
        assert result["items"][0]["status"] == "unknown"
        inspected = await tool.inspect_object_replacements(client, [GUID], UNID, 19723)
        assert inspected["objects"][0]["library"]["unid"] == UNID
        assert len(native["writes"]) == 1
        with pytest.raises(ValueError, match="consumed"):
            await tool.replace_object_libraries(
                client, [request()], 19723, False, preview["confirmation_token"]
            )


@pytest.mark.anyio
async def test_readback_must_match_not_just_success_response(native):
    native["drift"] = True
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as client:
        preview = await tool.replace_object_libraries(client, [request()], 19723)
        result = await tool.replace_object_libraries(
            client, [request()], 19723, False, preview["confirmation_token"]
        )
        assert result["items"][0]["status"] == "verification_failed"


@pytest.mark.anyio
async def test_missing_mount_and_duplicate_elements_refused(native):
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as client:
        bad = request()
        del bad["source_mount"]
        with pytest.raises(ValueError):
            await tool.replace_object_libraries(client, [bad], 19723)
        with pytest.raises(ValueError, match="only once"):
            await tool.replace_object_libraries(client, [request(), request()], 19723)
        assert not native["writes"]


@pytest.mark.anyio
async def test_apply_requires_explicit_port(native):
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as client:
        preview = await tool.replace_object_libraries(client, [request()], 19723)
        with pytest.raises(ValueError, match="explicit port"):
            await tool.replace_object_libraries(
                client, [request()], dry_run=False, confirmation_token=preview["confirmation_token"]
            )


@pytest.mark.anyio
async def test_read_only_index_resolution_returns_full_id(native):
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as client:
        data = await tool.inspect_object_replacements(client, [], port=19723, target_index=7)
        assert data["target"]["unid"] == UNID
        assert native["reads"] == [{"guids": [], "targetIndex": 7}]
        assert not native["writes"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    "kwargs",
    [{}, {"target_unid": UNID, "target_index": 7}, {"target_index": -1}, {"target_index": True}],
)
async def test_inspection_requires_one_valid_selector(native, kwargs):
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as client:
        with pytest.raises(ValueError):
            await tool.inspect_object_replacements(client, [], port=19723, **kwargs)
        assert not native["reads"] and not native["writes"]
