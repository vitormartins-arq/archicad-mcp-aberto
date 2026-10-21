import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import element_structure
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
GUID = "11111111-1111-1111-1111-111111111111"
MISSING = "33333333-3333-3333-3333-333333333333"


async def test_structure_reads_preserve_errors():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        a = await element_structure.get_subelements(client, [GUID, MISSING], 19723)
        b = await element_structure.get_element_trims(client, [GUID, MISSING], 19723)
        c = await element_structure.get_solid_operation_links(client, [GUID, MISSING], 19723)
        d = await element_structure.get_section_elements(client, [GUID], 19723)
    assert all(
        "error" in result[key][1]
        for result, key in ((a, "subelements"), (b, "elementTrims"), (c, "solidLinks"))
    )
    assert d["sectionElements"][0]["ownerElementType"] == "Wall"


@pytest.mark.parametrize("values", [[], [GUID] * 101, ["bad"]])
async def test_structure_limits(values):
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as client:
        with pytest.raises((ValueError, TypeError)):
            await element_structure.get_element_trims(client, values, 19723)
