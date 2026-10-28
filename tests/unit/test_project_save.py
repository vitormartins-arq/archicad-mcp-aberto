"""Offline native-boundary simulation and real temporary-file archival; no Archicad."""

from copy import deepcopy
from pathlib import Path

import pytest

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import project_save as save
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio


@pytest.fixture
def native(tmp_path, monkeypatch):
    source = tmp_path / "Example_R04.pln"
    source.write_bytes(b"OLD_DISK_REVISION")
    state = {
        "sessionId": "session",
        "projectEpoch": "project",
        "projectPath": str(source),
        "modificationStamp": "10",
        "untitled": False,
        "teamwork": False,
    }
    control = {"calls": 0, "mode": "ok"}
    journal = tmp_path / "receipts"
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(journal))

    async def addon(client, port, name, parameters=None, timeout=None):
        assert port == 19723
        if name == "GetProjectSaveContext":
            return deepcopy(state)
        assert name == "SaveProjectAsPLN"
        assert list(journal.rglob("*prepared*")), "Journal must precede native dispatch"
        assert all(parameters[k] == state[k] for k in state)
        path = Path(parameters["destinationPath"])
        assert not path.exists()
        control["calls"] += 1
        path.write_bytes(
            b"CURRENT_IN_MEMORY_WITH_UNSAVED_CHANGES" if control["mode"] != "empty" else b""
        )
        if control["mode"] != "wrong_path":
            state["projectPath"] = str(path)
        state["untitled"] = False
        state["modificationStamp"] = "11"
        if control["mode"] == "source_changed":
            source.write_bytes(b"EXTERNAL_CHANGE")
        if control["mode"] == "timeout":
            raise ArchicadError("Timeout after native dispatch")
        return deepcopy(state)

    monkeypatch.setattr(save.grids, "_addon", addon)
    return source, state, control


def client():
    return ArchicadClient(transport=fake_transport(FakeArchicad(19723)))


async def test_next_revision_saves_in_memory_before_archiving(native):
    source, state, control = native
    async with client() as c:
        plan = await save.save_next_project_revision(c, 19723)
        assert source.exists() and not source.with_name("00 - Anteriores").exists()
        result = await save.save_next_project_revision(c, 19723, False, plan["confirmation_token"])
        with pytest.raises(ValueError, match="consumed"):
            await save.save_next_project_revision(c, 19723, False, plan["confirmation_token"])
    destination = source.with_name("Example_R05.pln")
    assert destination.read_bytes() == b"CURRENT_IN_MEMORY_WITH_UNSAVED_CHANGES"
    assert (source.parent / "00 - Anteriores" / source.name).read_bytes() == b"OLD_DISK_REVISION"
    assert not source.exists() and control["calls"] == 1
    assert result["status"] == "verified"
    assert result["items"][0]["archive_verified"]
    assert "No project was saved" not in result["note"]
    assert state["projectPath"] == str(destination)


@pytest.mark.parametrize(
    "name,other,expected",
    [
        ("Example_R04.pln", "Example_R09.pln", "Example_R10.pln"),
        ("Example_REV099.pln", "Example_REV100.pln", "Example_REV101.pln"),
        ("Example.pln", "Example_R03.pln", "Example_R04.pln"),
        ("Example_R99.pln", "unrelated_R999.pln", "Example_R100.pln"),
        ("Example_R05_TEST.pln", "Example_R09_TEST.pln", "Example_R10_TEST.pln"),
        ("Example_R05_TEST.pln", "Example_R99_OTHER.pln", "Example_R06_TEST.pln"),
        ("Example_R01_REV005 Test.pln", "unrelated.pln", "Example_R01_REV006 Test.pln"),
    ],
)
async def test_revision_avoids_existing_current_and_archived_numbers(
    tmp_path, name, other, expected
):
    source = tmp_path / name
    source.write_bytes(b"source")
    archive = tmp_path / "00 - Anteriores"
    archive.mkdir()
    (archive / other).write_bytes(b"keep")
    assert save._revision_path(source, archive).name == expected
    assert (archive / other).read_bytes() == b"keep"


async def test_archive_collision_preserves_both_files(native):
    source, _, _ = native
    archive = source.parent / "00 - Anteriores"
    archive.mkdir()
    (archive / source.name).write_bytes(b"EXISTING_ARCHIVE")
    async with client() as c:
        plan = await save.save_next_project_revision(c, 19723)
        result = await save.save_next_project_revision(c, 19723, False, plan["confirmation_token"])
    assert result["status"] == "verified"
    assert (archive / source.name).read_bytes() == b"EXISTING_ARCHIVE"
    assert (archive / "Example_R04__archive_001.pln").read_bytes() == b"OLD_DISK_REVISION"


@pytest.mark.parametrize(
    "field,value",
    [
        ("sessionId", "restarted"),
        ("projectEpoch", "reopened"),
        ("modificationStamp", "12"),
        ("untitled", True),
    ],
)
async def test_context_change_refuses_apply(native, field, value):
    source, state, control = native
    async with client() as c:
        plan = await save.save_next_project_revision(c, 19723)
        state[field] = value
        with pytest.raises(ValueError):
            await save.save_next_project_revision(c, 19723, False, plan["confirmation_token"])
    assert source.exists() and control["calls"] == 0


async def test_destination_created_after_preview_is_never_overwritten(native):
    source, _, control = native
    async with client() as c:
        plan = await save.save_next_project_revision(c, 19723)
        destination = Path(plan["items"][0]["destination_path"])
        destination.write_bytes(b"OTHER_FILE")
        with pytest.raises(ValueError):
            await save.save_next_project_revision(c, 19723, False, plan["confirmation_token"])
    assert destination.read_bytes() == b"OTHER_FILE"
    assert source.exists() and control["calls"] == 0


@pytest.mark.parametrize("mode", ["timeout", "empty", "wrong_path", "source_changed"])
async def test_uncertain_save_or_verification_failure_never_archives(native, mode):
    source, _, control = native
    control["mode"] = mode
    async with client() as c:
        plan = await save.save_next_project_revision(c, 19723)
        result = await save.save_next_project_revision(c, 19723, False, plan["confirmation_token"])
        inspection = await save.inspect_project_save(c, plan["items"][0]["destination_path"], 19723)
    assert source.exists() and not (source.parent / "00 - Anteriores").exists()
    assert result["status"] == "needs_review" and control["calls"] == 1
    assert inspection["file"] is not None
    assert result["items"][0]["status"] == (
        "unknown" if mode == "timeout" else "verification_failed"
    )


async def test_archive_permission_failure_keeps_old_and_new(native, monkeypatch):
    source, _, _ = native

    def denied(*args):
        raise PermissionError("Archive locked")

    monkeypatch.setattr(save, "_move_no_replace", denied)
    async with client() as c:
        plan = await save.save_next_project_revision(c, 19723)
        result = await save.save_next_project_revision(c, 19723, False, plan["confirmation_token"])
    assert result["items"][0]["save_verified"] is True
    assert result["status"] == "needs_review" and source.exists()
    assert Path(plan["items"][0]["destination_path"]).exists()


async def test_explicit_save_of_untitled_project_does_not_archive(native):
    source, state, _ = native
    state.update(untitled=True, projectPath="")
    destination = source.with_name("First.pln")
    async with client() as c:
        with pytest.raises(ValueError, match="untitled"):
            await save.save_next_project_revision(c, 19723)
        plan = await save.save_project_as(c, str(destination), 19723)
        result = await save.save_project_as(
            c, str(destination), 19723, False, plan["confirmation_token"]
        )
    assert result["status"] == "verified" and source.exists()
    assert result["items"][0]["archive_path"] is None


async def test_teamwork_is_refused(native):
    _, state, control = native
    state["teamwork"] = True
    async with client() as c:
        with pytest.raises(ValueError, match="Teamwork"):
            await save.save_next_project_revision(c, 19723)
    assert control["calls"] == 0


async def test_existing_explicit_destination_is_refused(native):
    source, _, _ = native
    async with client() as c:
        with pytest.raises(ValueError, match="already exist"):
            await save.save_project_as(c, str(source), 19723)


async def test_move_refuses_existing_archive_destination(tmp_path):
    source, dest = tmp_path / "source.pln", tmp_path / "archive.pln"
    source.write_bytes(b"source")
    dest.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        save._move_no_replace(source, dest)
    assert source.read_bytes() == b"source" and dest.read_bytes() == b"existing"
