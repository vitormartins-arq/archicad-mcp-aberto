import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import zones_read as zones
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
ZONE = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
MISSING = "CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC"


def client(fake):
    return ArchicadClient(transport=fake_transport(fake))


async def test_zone_boundaries_preserve_rows_and_explicit_port():
    fake = FakeArchicad(19723)
    async with client(fake) as api:
        result = await zones.get_zone_boundaries(api, [ZONE, MISSING], 19723)
    assert result["port"] == 19723
    assert "zoneBoundaries" in result["zoneBoundariesOfZones"][0]
    assert "error" in result["zoneBoundariesOfZones"][1]
    assert fake.tapir_requests[-1]["parameters"]["zones"][0]["elementId"]["guid"] == ZONE


async def test_zone_relations_filter_and_errors():
    fake = FakeArchicad(19723)
    async with client(fake) as api:
        result = await zones.get_zone_relations(api, [ZONE, MISSING], "Wall", 19723)
    assert "elements" in result["relations"][0]
    assert "error" in result["relations"][1]
    assert fake.tapir_requests[-1]["parameters"]["otherElementType"] == "Wall"


@pytest.mark.parametrize("guids", [[], [ZONE] * 101, ["bad"]])
async def test_zone_read_rejects_invalid_batches(guids):
    async with client(FakeArchicad(19723)) as api:
        with pytest.raises((ValueError, TypeError)):
            await zones.get_zone_boundaries(api, guids, 19723)
