"""Simulated native contract. Real profile edits require an Archicad smoke test."""

from copy import deepcopy

import pytest

from archicad_mcp_aberto.tools import profile_modifiers as tool

from .test_read_tools import client, model

PROFILE = "12345678-1234-1234-1234-123456789000"
HEIGHT = "12345678-1234-1234-1234-123456789001"
DEPTH = "12345678-1234-1234-1234-123456789002"
NAME = "Altura do bit inferior"
pytestmark = pytest.mark.anyio


@pytest.fixture
def native(monkeypatch, tmp_path):
    context = {
        "sessionId": "session",
        "projectEpoch": "epoch",
        "projectPath": "",
        "modificationStamp": "1",
        "untitled": True,
        "teamwork": False,
    }
    snapshot = {
        "profileGuid": PROFILE,
        "geometryFingerprint": "same-geometry",
        "modifiers": [
            {
                "id": HEIGHT,
                "name": "H = BIT INFERIOR",
                "renamable": True,
                "setups": [{"edges": [{"direction": "left"}], "measurement": {"begin": {}}}],
            },
            {"id": DEPTH, "name": "P = BIT INFERIOR", "renamable": True, "setups": []},
        ],
    }
    requests = []
    response = {"status": "verified"}

    async def addon(c, port, command, params=None, timeout=None):
        assert port == 19723
        if command == "GetProjectSaveContext":
            return deepcopy(context)
        if command == "GetProfileModifiers":
            assert params == {"profileGuid": PROFILE}
            return deepcopy(snapshot)
        assert command == "RenameProfileModifiers"
        requests.append(params)
        return response

    monkeypatch.setattr(tool.grids, "_addon", addon)
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path / "receipts"))
    return context, snapshot, requests, response


async def test_preview_apply_by_id_and_consume_token(native):
    context, snapshot, requests, _ = native
    changes = [{"modifier_id": HEIGHT, "new_name": NAME}]
    async with client(model()) as c:
        read = await tool.get_profile_modifiers(c, PROFILE, 19723)
        assert read["modifiers"] == snapshot["modifiers"]
        preview = await tool.rename_profile_modifiers(c, PROFILE, changes, 19723)
        assert not requests
        token = preview["confirmation_token"]
        result = await tool.rename_profile_modifiers(c, PROFILE, changes, 19723, False, token)
        assert result["status"] == "verified"
        assert requests == [
            {
                "profileGuid": PROFILE,
                "context": context,
                "geometryFingerprint": "same-geometry",
                "renames": [{"id": HEIGHT, "oldName": "H = BIT INFERIOR", "newName": NAME}],
            }
        ]
        with pytest.raises(ValueError, match="already consumed"):
            await tool.rename_profile_modifiers(c, PROFILE, changes, 19723, False, token)


async def test_collision_between_distinct_ids_and_stale_geometry(native):
    _, snapshot, requests, _ = native
    async with client(model()) as c:
        with pytest.raises(ValueError, match="another modifier ID"):
            await tool.rename_profile_modifiers(
                c, PROFILE, [{"modifier_id": HEIGHT, "new_name": "p = bit inferior"}], 19723
            )
        changes = [{"modifier_id": HEIGHT, "new_name": NAME}]
        preview = await tool.rename_profile_modifiers(c, PROFILE, changes, 19723)
        snapshot["geometryFingerprint"] = "different-geometry"
        with pytest.raises(ValueError, match="changed since preview"):
            await tool.rename_profile_modifiers(
                c, PROFILE, changes, 19723, False, preview["confirmation_token"]
            )
    assert not requests


@pytest.mark.parametrize(
    "status, expected", [("restored", "verification_failed"), ("unknown", "unknown")]
)
async def test_native_readback_failure_is_not_a_success(native, status, expected):
    _, _, requests, response = native
    response["status"] = status
    changes = [{"modifier_id": HEIGHT, "new_name": NAME}]
    async with client(model()) as c:
        preview = await tool.rename_profile_modifiers(c, PROFILE, changes, 19723)
        result = await tool.rename_profile_modifiers(
            c, PROFILE, changes, 19723, False, preview["confirmation_token"]
        )
    assert len(requests) == 1
    assert result["status"] == "needs_review"
    assert result["items"][0]["status"] == expected
