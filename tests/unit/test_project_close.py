"""Offline protocol mocks only: these do not prove native Close runtime support."""

from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import project_close as close
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio


@pytest.fixture
def native(tmp_path, monkeypatch):
    source = tmp_path / "Example_R01.pln"
    source.write_bytes(b"existing PLN")
    state = {
        "sessionId": "session",
        "projectEpoch": "epoch",
        "projectPath": str(source),
        "modificationStamp": "1",
        "untitled": False,
        "teamwork": False,
    }
    control = {"calls": [], "mode": "ok"}
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path / "receipts"))

    async def addon(client, port, name, parameters=None, timeout=None):
        assert port == 19723
        if name == "GetProjectSaveContext":
            if control["mode"] == "busy":
                raise ArchicadError("Busy", code=4001)
            return deepcopy(state)
        control["calls"].append(name)
        if name == "PrepareProjectClose":
            assert parameters["projectPath"] == state["projectPath"]
            if control["mode"] == "save_failure":
                raise ArchicadError("Save failed")
            source.write_bytes(b"CURRENT MEMORY SAVED" if control["mode"] != "empty" else b"")
            state["modificationStamp"] = "2"
            result = {
                **state,
                "closeToken": "native-token",
                "savedFileSize": str(source.stat().st_size),
            }
            if control["mode"] == "context_changed":
                state["modificationStamp"] = "3"
            if control["mode"] == "wrong_identity":
                state["projectEpoch"] = "OTHER"
                result["projectEpoch"] = "OTHER"
            if control["mode"] == "missing_proof":
                result.pop("closeToken")
            if control["mode"] == "wrong_size":
                result["savedFileSize"] = "999"
            return result
        assert name == "ClosePreparedProject"
        assert parameters == {
            **{
                k: state[k]
                for k in ("sessionId", "projectEpoch", "projectPath", "modificationStamp")
            },
            "closeToken": "native-token",
        }
        saved = list((tmp_path / "receipts").rglob("*saved*"))
        assert saved, "Verified save receipt must precede close"
        if control["mode"] == "close_timeout":
            raise ArchicadError("Connection lost")
        return {
            "closeReturnedNoError": True,
            "noOpenProject": control["mode"] != "readback_failed",
            "readBackError": 0,
        }

    monkeypatch.setattr(close.grids, "_addon", addon)
    return source, state, control


def client():
    c = ArchicadClient(transport=fake_transport(FakeArchicad(19723)))
    original = c.command

    async def command(port, name, parameters=None, **kwargs):
        if name == "IsAddOnCommandAvailable":
            return {"isAvailable": True}
        return await original(port, name, parameters, **kwargs)

    c.command = command
    return c


async def test_preview_never_saves_or_closes(native):
    source, state, control = native
    async with client() as c:
        r = await close.save_and_close_project(c, 19723)
    assert r["dry_run"] and r["target"]["project"] == state
    assert source.read_bytes() == b"existing PLN"
    assert control["calls"] == []


async def test_verified_same_path_no_extra_revision_and_one_use(native):
    source, state, control = native
    async with client() as c:
        p = await close.save_and_close_project(c, 19723)
        r = await close.save_and_close_project(c, 19723, False, p["confirmation_token"])
        with pytest.raises(ValueError, match="consumed"):
            await close.save_and_close_project(c, 19723, False, p["confirmation_token"])
    assert r["status"] == "verified"
    item = r["items"][0]
    assert item["save_verified"] and item["close_verified"]
    assert len(item["saved_sha256"]) == 64
    assert list(source.parent.glob("*.pln")) == [source]
    assert control["calls"] == ["PrepareProjectClose", "ClosePreparedProject"]


@pytest.mark.parametrize(
    "mode",
    ["save_failure", "empty", "context_changed", "wrong_identity", "missing_proof", "wrong_size"],
)
async def test_failed_save_or_proof_never_closes(native, mode):
    source, state, control = native
    async with client() as c:
        p = await close.save_and_close_project(c, 19723)
        control["mode"] = mode
        r = await close.save_and_close_project(c, 19723, False, p["confirmation_token"])
    assert r["status"] == "needs_review"
    assert not r["items"][0]["close_dispatched"]
    assert control["calls"] == ["PrepareProjectClose"]


@pytest.mark.parametrize("field", ["sessionId", "projectEpoch", "projectPath", "modificationStamp"])
async def test_stale_preview_rejects_without_native_write(native, field):
    source, state, control = native
    async with client() as c:
        p = await close.save_and_close_project(c, 19723)
        state[field] = (
            "123"
            if field == "modificationStamp"
            else str(source) + ".pln"
            if field == "projectPath"
            else "changed"
        )
        with pytest.raises(ValueError):
            await close.save_and_close_project(c, 19723, False, p["confirmation_token"])
    assert not control["calls"]


async def test_disconnect_is_unknown_not_success_and_not_replayed(native):
    source, state, control = native
    async with client() as c:
        p = await close.save_and_close_project(c, 19723)
        control["mode"] = "close_timeout"
        r = await close.save_and_close_project(c, 19723, False, p["confirmation_token"])
        with pytest.raises(ValueError):
            await close.save_and_close_project(c, 19723, False, p["confirmation_token"])
    assert r["status"] == "needs_review"
    assert r["items"][0]["save_verified"]
    assert not r["items"][0]["close_verified"]
    assert r["items"][0]["status"] == "unknown"


async def test_no_open_project_must_be_confirmed(native):
    source, state, control = native
    async with client() as c:
        p = await close.save_and_close_project(c, 19723)
        control["mode"] = "readback_failed"
        r = await close.save_and_close_project(c, 19723, False, p["confirmation_token"])
    assert r["status"] == "needs_review" and not r["items"][0]["close_verified"]


async def test_explicit_port_required_and_old_addon_refused(native):
    async with client() as c:
        with pytest.raises(ValueError, match="explicit"):
            await close.save_and_close_project(c)

        async def unavailable(*args, **kwargs):
            return {"isAvailable": False}

        c.command = unavailable
        with pytest.raises(ValueError, match="unavailable"):
            await close.save_and_close_project(c, 19723)
    assert native[2]["calls"] == []


@pytest.mark.parametrize("kind", ["untitled", "teamwork"])
async def test_unsupported_project_refused(native, kind):
    native[1][kind] = True
    async with client() as c:
        with pytest.raises(ValueError):
            await close.save_and_close_project(c, 19723)
    assert native[2]["calls"] == []


async def test_busy_aborts_without_close(native):
    native[2]["mode"] = "busy"
    async with client() as c:
        with pytest.raises(ArchicadError):
            await close.save_and_close_project(c, 19723)
    assert native[2]["calls"] == []


async def test_file_changed_during_hash_aborts_close(native, monkeypatch):
    source, state, control = native
    original = close.model_tasks._hash

    def changing_hash(path):
        result = original(path)
        source.write_bytes(b"external change during verification")
        return result

    monkeypatch.setattr(close.model_tasks, "_hash", changing_hash)
    async with client() as c:
        p = await close.save_and_close_project(c, 19723)
        r = await close.save_and_close_project(c, 19723, False, p["confirmation_token"])
    assert not r["items"][0]["close_dispatched"]
    assert control["calls"] == ["PrepareProjectClose"]


async def test_save_receipt_failure_aborts_close(native, monkeypatch):
    source, state, control = native
    original = close.write._journal

    def journal(receipt, stage):
        if stage == "saved":
            raise OSError("Cannot persist save receipt")
        return original(receipt, stage)

    monkeypatch.setattr(close.write, "_journal", journal)
    async with client() as c:
        p = await close.save_and_close_project(c, 19723)
        r = await close.save_and_close_project(c, 19723, False, p["confirmation_token"])
    assert r["items"][0]["save_verified"]
    assert not r["items"][0]["close_dispatched"]
    assert control["calls"] == ["PrepareProjectClose"]
