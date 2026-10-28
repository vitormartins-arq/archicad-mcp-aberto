import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import ifc
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
ELEMENT = "11111111-1111-1111-1111-111111111111"
MISSING = "22222222-2222-2222-2222-222222222222"
IFC_ID = "2O2Fr$t4X7Zf8NOew3FNvQ"


def client(fake):
    return ArchicadClient(transport=fake_transport(fake))


async def test_get_ifc_of_elements_preserves_all_three_aligned_results():
    fake = FakeArchicad(19723)
    async with client(fake) as api:
        result = await ifc.get_ifc_of_elements(api, [ELEMENT, MISSING], 19723)
    assert result["elementIFCTypes"][0]["ifcType"] == "IfcWall"
    assert result["elementIFCIds"][0]["ifcId"] == IFC_ID
    assert "ifcProperties" in result["elementIFCProperties"][0]
    assert all(
        "error" in result[key][1]
        for key in ("elementIFCTypes", "elementIFCIds", "elementIFCProperties")
    )


async def test_find_elements_by_ifc_ids_keeps_input_rows():
    fake = FakeArchicad(19723)
    async with client(fake) as api:
        result = await ifc.find_elements_by_ifc_ids(api, [IFC_ID, "missing"], 19723)
    assert result["elementsByIFCIds"][0]["elements"][0]["elementId"]["guid"] == ELEMENT
    assert result["elementsByIFCIds"][1] == {"ifcId": "missing", "elements": []}


@pytest.mark.parametrize("values", [[], [ELEMENT] * 101, ["bad-guid"]])
async def test_get_ifc_rejects_invalid_batches(values):
    async with client(FakeArchicad(19723)) as api:
        with pytest.raises((ValueError, TypeError)):
            await ifc.get_ifc_of_elements(api, values, 19723)
