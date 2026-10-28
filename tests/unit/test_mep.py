import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import mep
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio


async def test_mep_reads_use_all_source_commands():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        systems = await mep.list_mep_systems(client, 19723)
        elements = await mep.get_mep_elements(client, domains=["Piping"], port=19723)
        tables = await mep.get_mep_preference_tables(client, "Piping", 19723)
    assert systems["mepSystems"][0]["domain"] == "Piping"
    assert elements["elements"][0]["type"] == "RoutingElement"
    assert tables["tables"][0]["rows"][0]["diameter"] == 0.1
    assert {
        "GetMEPSystems",
        "GetMEPDistributionSystems",
        "GetMEPElements",
        "GetMEPRoutingElements",
        "GetMEPPorts",
        "GetMEPPreferenceTables",
    } <= set(fake.tapir_calls)


@pytest.mark.parametrize("limit", [0, 101])
async def test_mep_limits(limit):
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as client:
        with pytest.raises(ValueError):
            await mep.get_mep_elements(client, limit=limit, port=19723)
