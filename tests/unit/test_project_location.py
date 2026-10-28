import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import project_location
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
LAYOUT = "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"
MISSING = "CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC"


def client(fake):
    return ArchicadClient(transport=fake_transport(fake))


async def test_project_location_combines_geo_and_units_on_explicit_port():
    fake = FakeArchicad(19723)
    async with client(fake) as api:
        result = await project_location.get_project_location(api, 19723)
    assert result["projectLocation"]["north"] == 0.25
    assert result["calculationUnits"]["length"]["unit"] == "Meter"
    assert fake.tapir_calls[-2:] == ["GetGeoLocation", "GetCalculationUnits"]


async def test_layout_settings_preserve_per_layout_errors():
    fake = FakeArchicad(19723)
    async with client(fake) as api:
        result = await project_location.get_layout_settings(api, [LAYOUT, MISSING], 19723)
    assert result["layoutSettings"][0]["layoutName"] == "A-01 Floor Plan"
    assert "error" in result["layoutSettings"][1]
    assert fake.tapir_requests[-1]["parameters"]["layoutDatabaseIds"][0] == {
        "databaseId": {"guid": LAYOUT}
    }


@pytest.mark.parametrize("values", [[], [LAYOUT] * 101, ["bad"]])
async def test_layout_settings_reject_invalid_batches(values):
    async with client(FakeArchicad(19723)) as api:
        with pytest.raises((ValueError, TypeError)):
            await project_location.get_layout_settings(api, values, 19723)
