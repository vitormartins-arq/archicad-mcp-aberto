"""Offline task checkpoints use temp PLNs and a simulated native save boundary."""

from copy import deepcopy
from pathlib import Path

import pytest

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import model_tasks as tasks
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio


@pytest.fixture
def native_task(tmp_path, monkeypatch):
    source = tmp_path / "Working.pln"
    source.write_bytes(b"LAST_SAVED_DISK")
    context = dict(
        sessionId="native",
        projectEpoch="project",
        projectPath=str(source),
        modificationStamp="1",
        untitled=False,
        teamwork=False,
    )
    state = dict(
        context=context,
        source=source,
        pending=b"UNSAVED_BEFORE_TASK",
        saves=0,
        calls=[],
        timeout=False,
        receipts=tmp_path / "receipts",
    )
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(state["receipts"]))

    async def pause(_):
        if state.get("view_updates"):
            context["modificationStamp"] = str(state["view_updates"].pop(0))

    monkeypatch.setattr(tasks, "_settle_pause", pause)

    async def addon(client, port, name, parameters=None, timeout=None):
        assert port == 19723
        state["calls"].append(name)
        if name == "GetProjectSaveContext":
            return deepcopy(context)
        assert name == "SaveCurrentProjectPLN"
        assert parameters == {"destinationPath": context["projectPath"], **context}
        assert list(state["receipts"].glob("*.prepared.json"))
        state["saves"] += 1
        source.write_bytes(state["pending"])
        context["modificationStamp"] = str(int(context["modificationStamp"]) + 1)
        if state["timeout"]:
            raise ArchicadError("Native save timed out after writing")
        return deepcopy(context)

    state["addon"] = addon
    monkeypatch.setattr(tasks.grids, "_addon", addon)
    return state


def client():
    return ArchicadClient(transport=fake_transport(FakeArchicad(19723)))


async def checkpoint(c):
    preview = await tasks.begin_model_task(c, 19723)
    return await tasks.begin_model_task(c, 19723, False, preview["confirmation_token"])


async def finish(c, token):
    preview = await tasks.finish_model_task(c, token, 19723)
    return await tasks.finish_model_task(c, token, 19723, False, preview["confirmation_token"])


async def test_checkpoint_includes_unsaved_state_and_saves_result_in_same_file(native_task):
    state = native_task
    async with client() as c:
        ready = await checkpoint(c)
        assert ready["status"] == "verified"
        item = ready["items"][0]
        assert Path(item["disk_backup_proof"]["path"]).read_bytes() == b"LAST_SAVED_DISK"
        assert Path(item["backup"]["path"]).read_bytes() == b"UNSAVED_BEFORE_TASK"
        state["pending"] = b"AFTER_REQUESTED_MODEL_CHANGES"
        result = await finish(c, ready["task_token"])
    assert result["status"] == "verified" and state["saves"] == 2
    assert state["source"].name == "Working.pln"
    assert state["source"].read_bytes() == b"AFTER_REQUESTED_MODEL_CHANGES"
    assert Path(item["backup"]["path"]).read_bytes() == b"UNSAVED_BEFORE_TASK"


async def test_checkpoint_preview_has_no_save_or_files(native_task):
    async with client() as c:
        preview = await tasks.begin_model_task(c, 19723)
    assert preview["dry_run"] is True and native_task["saves"] == 0
    assert not (native_task["source"].parent / "Anteriores").exists()


async def test_changed_context_prevents_checkpoint_apply(native_task):
    async with client() as c:
        preview = await tasks.begin_model_task(c, 19723)
        native_task["context"]["projectEpoch"] = "different-project"
        with pytest.raises(ValueError):
            await tasks.begin_model_task(c, 19723, False, preview["confirmation_token"])
    assert native_task["saves"] == 0


async def test_unknown_checkpoint_never_authorizes_task(native_task):
    native_task["timeout"] = True
    async with client() as c:
        result = await checkpoint(c)
    assert result["status"] == "needs_review" and "task_token" not in result
    assert result["items"][0]["status"] == "unknown"
    assert Path(result["items"][0]["disk_backup_proof"]["path"]).read_bytes() == b"LAST_SAVED_DISK"


async def test_unknown_final_save_cannot_be_retried_with_new_preview(native_task):
    async with client() as c:
        ready = await checkpoint(c)
        native_task["timeout"] = True
        result = await finish(c, ready["task_token"])
        assert result["items"][0]["status"] == "unknown"
        with pytest.raises(ValueError, match="already attempted"):
            await tasks.finish_model_task(c, ready["task_token"], 19723)
    assert native_task["saves"] == 2


@pytest.mark.parametrize("change", ["backup", "disk", "project", "session"])
async def test_finish_refuses_changed_backup_file_project_or_session(native_task, change):
    async with client() as c:
        ready = await checkpoint(c)
        if change == "backup":
            Path(ready["items"][0]["backup"]["path"]).write_bytes(b"ALTERED_BACKUP")
        elif change == "disk":
            native_task["source"].write_bytes(b"EXTERNAL_DISK_CHANGE")
        elif change == "project":
            native_task["context"]["projectEpoch"] = "reopened"
        else:
            c.session_id = "another-client-session"
        with pytest.raises(ValueError):
            await tasks.finish_model_task(c, ready["task_token"], 19723)
    assert native_task["saves"] == 1


async def test_copy_never_replaces_existing_backup(tmp_path):
    source, dest = tmp_path / "source.pln", tmp_path / "backup.pln"
    source.write_bytes(b"source")
    dest.write_bytes(b"preserve")
    with pytest.raises(FileExistsError):
        tasks._copy_verified(source, dest)
    assert dest.read_bytes() == b"preserve" and source.read_bytes() == b"source"


async def test_settled_context_waits_for_deferred_view_notifications(native_task):
    native_task["view_updates"] = [2, 3, 3, 3]
    async with client() as c:
        result = await tasks._settled_context(c, 19723)
    assert result["modificationStamp"] == "3"
    assert native_task["saves"] == 0


async def test_continuously_changing_project_never_dispatches_save(native_task):
    native_task["view_updates"] = list(range(2, 20))
    async with client() as c:
        with pytest.raises(ValueError, match="not settled"):
            await tasks.begin_model_task(c, 19723)
    assert native_task["saves"] == 0
    assert not (native_task["source"].parent / "Anteriores").exists()


async def test_project_switch_during_settling_is_rejected(native_task, monkeypatch):
    async def switched(_):
        native_task["context"]["projectEpoch"] = "other-project"

    monkeypatch.setattr(tasks, "_settle_pause", switched)
    async with client() as c:
        with pytest.raises(ValueError, match="Project/session changed"):
            await tasks.begin_model_task(c, 19723)
    assert native_task["saves"] == 0
