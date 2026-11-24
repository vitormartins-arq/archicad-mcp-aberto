"""Contract mocks only: no real Archicad or group-edit success is claimed."""

from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import groups
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio


@pytest.fixture
def native(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPT_DIR", str(tmp_path))
    state = {
        "suspended": False,
        "context": {
            "sessionId": "session",
            "projectEpoch": "epoch",
            "projectPath": "test.pln",
            "modificationStamp": "1",
            "untitled": False,
            "teamwork": False,
        },
    }
    control = {"state": state, "calls": [], "mode": "ok"}

    async def addon(client, port, name, params=None, timeout=None):
        assert port == 19723
        control["calls"].append((name, deepcopy(params)))
        if name == "GetSuspendGroups":
            return deepcopy(state)
        assert name == "SetSuspendGroups"
        assert params["expectedState"] == state
        if control["mode"] == "timeout":
            raise ArchicadError("Unknown native outcome")
        previous = state["suspended"]
        if control["mode"] != "refused":
            state["suspended"] = params["suspended"]
        if control["mode"] == "wrong_project":
            state["context"]["projectEpoch"] = "another"
        return {
            "previousSuspended": previous,
            "suspended": state["suspended"],
            "verified": True,
            "state": deepcopy(state),
        }

    monkeypatch.setattr(groups.grids, "_addon", addon)
    return control


def client():
    return ArchicadClient(transport=fake_transport(FakeArchicad(19723)))


async def test_read_and_preview_do_not_write(native):
    async with client() as c:
        assert (await groups.get_suspend_groups(c, 19723))["suspended"] is False
        plan = await groups.set_suspend_groups(c, True, 19723)
    assert plan["dry_run"] and plan["restore_suspended"] is False
    assert all(name == "GetSuspendGroups" for name, _ in native["calls"])


async def test_apply_restore_and_single_use_token(native):
    async with client() as c:
        p = await groups.set_suspend_groups(c, True, 19723)
        r = await groups.set_suspend_groups(c, True, 19723, False, p["confirmation_token"])
        assert r["status"] == "verified"
        assert native["state"]["suspended"] is True
        with pytest.raises(ValueError, match="consumed"):
            await groups.set_suspend_groups(c, True, 19723, False, p["confirmation_token"])
        # Editing may change the stamp; restoring MUST use a fresh preview.
        native["state"]["context"]["modificationStamp"] = "2"
        p = await groups.set_suspend_groups(c, r["restore_suspended"], 19723)
        r = await groups.set_suspend_groups(c, False, 19723, False, p["confirmation_token"])
        assert r["status"] == "verified" and native["state"]["suspended"] is False
    assert {name for name, _ in native["calls"]} == {"GetSuspendGroups", "SetSuspendGroups"}


@pytest.mark.parametrize("change", ["mode", "stamp", "epoch", "path", "desired"])
async def test_stale_previews_refuse_before_write(native, change):
    async with client() as c:
        p = await groups.set_suspend_groups(c, True, 19723)
        desired = True
        if change == "mode":
            native["state"]["suspended"] = True
        elif change == "desired":
            desired = False
        else:
            key = {"stamp": "modificationStamp", "epoch": "projectEpoch", "path": "projectPath"}[
                change
            ]
            native["state"]["context"][key] = "changed"
        with pytest.raises(ValueError, match="changed"):
            await groups.set_suspend_groups(c, desired, 19723, False, p["confirmation_token"])
    assert all(name == "GetSuspendGroups" for name, _ in native["calls"])


@pytest.mark.parametrize("mode", ["refused", "wrong_project", "timeout"])
async def test_failed_readback_and_unknown_are_not_success(native, mode):
    async with client() as c:
        p = await groups.set_suspend_groups(c, True, 19723)
        native["mode"] = mode
        r = await groups.set_suspend_groups(c, True, 19723, False, p["confirmation_token"])
        assert r["status"] == "needs_review"
        assert r["items"][0]["status"] in {"verification_failed", "unknown"}
        with pytest.raises(ValueError, match="consumed"):
            await groups.set_suspend_groups(c, True, 19723, False, p["confirmation_token"])


async def test_noop_and_explicit_port(native):
    async with client() as c:
        p = await groups.set_suspend_groups(c, False, 19723)
        with pytest.raises(ValueError, match="explicit port"):
            await groups.set_suspend_groups(c, False, None, False, p["confirmation_token"])
        r = await groups.set_suspend_groups(c, False, 19723, False, p["confirmation_token"])
        assert r["status"] == "verified" and r["restore_suspended"] is False


@pytest.mark.parametrize("value", [1, "true", None])
async def test_strict_boolean(native, value):
    async with client() as c:
        with pytest.raises(ValueError, match="boolean"):
            await groups.set_suspend_groups(c, value, 19723)
    assert not native["calls"]


async def test_missing_identity_fails_closed(native):
    del native["state"]["context"]["sessionId"]
    async with client() as c:
        with pytest.raises(ValueError, match="identity"):
            await groups.set_suspend_groups(c, True, 19723)
