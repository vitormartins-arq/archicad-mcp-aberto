"""Save As and the next-revision routine through the add-on, against the simulated Archicad."""

import os
from pathlib import Path

import pytest

from archicad_mcp_aberto.connection import AddOnError, ArchicadClient
from archicad_mcp_aberto.tools import project_save
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path / "receipts"))


def project(folder: Path, name: str = "WG Formosa_R04.pln", **kwargs) -> FakeArchicad:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(b"PLN revision")
    return FakeArchicad(19723, project_path=str(folder / name), **kwargs)


async def revision(c, **kwargs):
    preview = await project_save.save_next_project_revision(c, 19723, **kwargs)
    return preview, await project_save.save_next_project_revision(
        c, 19723, dry_run=False, confirmation_token=preview["confirmation_token"], **kwargs
    )


async def test_next_revision_saves_r05_and_moves_r04_to_the_archive(tmp_path):
    fake = project(tmp_path / "BIM")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await revision(c)
    r05 = tmp_path / "BIM" / "WG Formosa_R05.pln"
    moved = tmp_path / "BIM" / "00 - Anteriores" / "WG Formosa_R04.pln"
    assert preview["dry_run"] and preview["items"][0]["destination_path"] == str(r05)
    assert preview["items"][0]["archive_path"] == str(moved)
    assert result["status"] == "verified"
    item = result["items"][0]
    assert item["save_verified"] and item["archive_verified"]
    assert fake.project_path == str(r05) and r05.read_bytes()
    assert moved.read_bytes() == b"PLN revision"
    assert not (tmp_path / "BIM" / "WG Formosa_R04.pln").exists()
    assert fake.own_addon_calls.count("SaveProjectAsPLN") == 1
    request = fake.own_addon_requests[-2]["parameters"]
    assert request["expectedProjectPath"] == str(tmp_path / "BIM" / "WG Formosa_R04.pln")
    assert "cannot be undone" in result["note"]


async def test_preview_changes_nothing(tmp_path):
    fake = project(tmp_path)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        await project_save.save_next_project_revision(c, 19723)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["WG Formosa_R04.pln"]
    assert "SaveProjectAsPLN" not in fake.own_addon_calls


@pytest.mark.parametrize(
    ("name", "existing", "expected"),
    [
        ("WG Formosa.pln", [], "WG Formosa_R01.pln"),
        ("Casa REV9.pln", [], "Casa REV10.pln"),
        ("Loja-r4.pln", [], "Loja-r05.pln"),
        ("Casa_R04.pln", ["00 - Anteriores/Casa_R05.pln"], "Casa_R06.pln"),
        ("Casa_R04.pln", ["Casa_R07.pln", "Outra_R09.pln"], "Casa_R08.pln"),
    ],
)
def test_next_revision_name(tmp_path, name, existing, expected):
    for relative in existing:
        (tmp_path / relative).parent.mkdir(exist_ok=True)
        (tmp_path / relative).write_bytes(b"x")
    source = tmp_path / name
    assert project_save.next_revision(source, tmp_path / "00 - Anteriores").name == expected


async def test_custom_archive_folder(tmp_path):
    fake = project(tmp_path)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await revision(c, archive_folder="Anteriores")
    assert result["status"] == "verified"
    assert (tmp_path / "Anteriores" / "WG Formosa_R04.pln").exists()


async def test_existing_archived_copy_is_refused_before_saving(tmp_path):
    fake = project(tmp_path)
    (tmp_path / "00 - Anteriores").mkdir()
    (tmp_path / "00 - Anteriores" / "WG Formosa_R04.pln").write_bytes(b"old")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="already exists"):
            await project_save.save_next_project_revision(c, 19723)
    assert "SaveProjectAsPLN" not in fake.own_addon_calls


async def test_untitled_project_needs_save_as_first(tmp_path):
    fake = FakeArchicad(19723)
    target = tmp_path / "Novo projeto.pln"
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="never saved"):
            await project_save.save_next_project_revision(c, 19723)
        preview = await project_save.save_project_as(c, str(target), 19723)
        result = await project_save.save_project_as(
            c, str(target), 19723, False, preview["confirmation_token"]
        )
    assert result["status"] == "verified" and target.exists()
    assert fake.own_addon_requests[-2]["parameters"]["expectedProjectPath"] == ""
    assert "archive_path" not in result["items"][0]


@pytest.mark.parametrize(
    ("destination", "error"),
    [
        ("relative.pln", "absolute"),
        ("{tmp}/copy.tpl", "absolute"),
        ("{tmp}/WG Formosa_R04.pln", "already exists|new file name"),
        ("{tmp}/missing folder/x.pln", "does not exist"),
        ("{tmp}/../x.pln", "absolute"),
    ],
)
async def test_save_as_refuses_bad_destinations(tmp_path, destination, error):
    fake = project(tmp_path)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match=error):
            await project_save.save_project_as(c, destination.format(tmp=tmp_path), 19723)


async def test_teamwork_is_refused(tmp_path):
    fake = project(tmp_path, project_teamwork=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="Teamwork"):
            await project_save.save_next_project_revision(c, 19723)


async def test_another_project_opened_after_preview_is_refused(tmp_path):
    fake = project(tmp_path)
    other = tmp_path / "Outro_R01.pln"
    other.write_bytes(b"x")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await project_save.save_next_project_revision(c, 19723)
        fake.project_path = str(other)
        with pytest.raises(ValueError, match="changed since preview"):
            await project_save.save_next_project_revision(
                c, 19723, dry_run=False, confirmation_token=preview["confirmation_token"]
            )
    assert "SaveProjectAsPLN" not in fake.own_addon_calls


async def test_previous_file_changed_after_preview_needs_a_new_preview(tmp_path):
    fake = project(tmp_path)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await project_save.save_next_project_revision(c, 19723)
        (tmp_path / "WG Formosa_R04.pln").write_bytes(b"saved again with Ctrl+S")
        with pytest.raises(ValueError, match="changed since preview"):
            await project_save.save_next_project_revision(
                c, 19723, dry_run=False, confirmation_token=preview["confirmation_token"]
            )


async def test_lost_save_answer_is_unknown_and_nothing_is_moved(tmp_path):
    fake = project(tmp_path, lose_save_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await revision(c)
        with pytest.raises(ValueError, match="already consumed"):
            await project_save.save_next_project_revision(
                c, 19723, dry_run=False, confirmation_token=preview["confirmation_token"]
            )
    assert result["items"][0]["status"] == "unknown"
    assert "do not retry" in result["warning"]
    assert (tmp_path / "WG Formosa_R04.pln").exists()
    assert not (tmp_path / "00 - Anteriores").exists()


async def test_add_on_refusal_is_a_failure_and_nothing_is_moved(tmp_path):
    fake = project(tmp_path)
    fake.own_addon_errors.add("SaveProjectAsPLN")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await revision(c)
    assert result["items"][0]["status"] == "failed"
    assert (tmp_path / "WG Formosa_R04.pln").exists()
    assert not (tmp_path / "WG Formosa_R05.pln").exists()


async def test_failed_move_keeps_the_saved_revision_and_says_so(tmp_path, monkeypatch):
    fake = project(tmp_path)

    def locked(source, destination):
        raise PermissionError("in use")

    monkeypatch.setattr(project_save, "_move", locked)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await revision(c)
    item = result["items"][0]
    assert item["status"] == "verification_failed" and item["save_verified"]
    assert item["archive_verified"] is False and "Move it by hand" in item["error"]
    assert (tmp_path / "WG Formosa_R05.pln").exists()
    assert (tmp_path / "WG Formosa_R04.pln").exists()


async def test_missing_add_on_is_reported(tmp_path):
    fake = project(tmp_path, own_addon_loaded=False)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(AddOnError):
            await project_save.save_next_project_revision(c, 19723)


@pytest.mark.skipif(os.name != "nt", reason="Windows rename semantics")
def test_move_never_replaces_on_windows(tmp_path):
    (tmp_path / "a.pln").write_bytes(b"a")
    (tmp_path / "b.pln").write_bytes(b"b")
    with pytest.raises(FileExistsError):
        project_save._move(tmp_path / "a.pln", tmp_path / "b.pln")
