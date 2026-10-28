"""Project Map renames (RenameProjectMapItems of our add-on), against the simulated Archicad."""

import pytest

from archicad_mcp_aberto.connection import AddOnError, ArchicadClient
from archicad_mcp_aberto.tools import project_map_names
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
ONE, TWO = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA", "BBBBBBBB-BBBB-4BBB-8BBB-BBBBBBBBBBBB"


def model(**extra):
    return FakeArchicad(19723, project_map_names={ONE: "Câmera 1", TWO: "Câmera 2"}, **extra)


def client(fake):
    return ArchicadClient(ports=(19723,), transport=fake_transport(fake))


async def test_cameras_are_listed_and_renamed_with_read_back():
    fake = model()
    items = [{"guid": ONE.lower(), "name": "1 RECEPÇÃO - 2P 01"}, {"guid": TWO, "name": "2 SALA"}]
    async with client(fake) as c:
        listed = await project_map_names.list_project_map_cameras(c)
        preview = await project_map_names.rename_project_map_items(c, items)
        assert fake.project_map_names[ONE] == "Câmera 1"
        result = await project_map_names.rename_project_map_items(
            c, items, port=19723, dry_run=False, confirmation_token=preview["confirmation_token"]
        )
    assert listed["count"] == 2 and listed["cameras"][0]["path"] == "00 BIMx - Apresentação"
    assert [i["before"] for i in preview["items"]] == ["Câmera 1", "Câmera 2"]
    assert [i["status"] for i in result["items"]] == ["verified", "verified"]
    assert fake.project_map_names == {ONE: "1 RECEPÇÃO - 2P 01", TWO: "2 SALA"}


async def test_refused_name_is_failed_and_token_is_single_use():
    fake = model(project_map_refused={TWO})
    items = [{"guid": ONE, "name": "A"}, {"guid": TWO, "name": "B"}]
    async with client(fake) as c:
        preview = await project_map_names.rename_project_map_items(c, items)
        token = preview["confirmation_token"]
        result = await project_map_names.rename_project_map_items(
            c, items, port=19723, dry_run=False, confirmation_token=token
        )
        with pytest.raises(ValueError, match="consumed"):
            await project_map_names.rename_project_map_items(
                c, items, port=19723, dry_run=False, confirmation_token=token
            )
        with pytest.raises(ValueError, match="explicit port"):
            await project_map_names.rename_project_map_items(c, items, dry_run=False)
    assert [i["status"] for i in result["items"]] == ["verified", "failed"]


async def test_bad_items_are_refused_before_archicad():
    for bad in ([], [{"guid": "x", "name": "A"}], [{"guid": ONE, "name": " "}],
                [{"guid": ONE, "name": "A"}, {"guid": ONE, "name": "B"}]):  # fmt: skip
        with pytest.raises(ValueError):
            await project_map_names.rename_project_map_items(None, bad)


async def test_missing_addon_says_how_to_install():
    async with client(model(own_addon_loaded=False)) as c:
        with pytest.raises(AddOnError, match="Add-On Manager"):
            await project_map_names.list_project_map_cameras(c)
