"""Project Map camera list (GetCameraViews of our add-on), against the simulated Archicad."""

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


async def test_cameras_are_listed_with_their_path():
    async with client(model()) as c:
        listed = await project_map_names.list_project_map_cameras(c)
    assert listed["count"] == 2 and listed["cameras"][0]["path"] == "00 BIMx - Apresentação"


async def test_missing_addon_says_how_to_install():
    async with client(model(own_addon_loaded=False)) as c:
        with pytest.raises(AddOnError, match="Add-On Manager"):
            await project_map_names.list_project_map_cameras(c)
