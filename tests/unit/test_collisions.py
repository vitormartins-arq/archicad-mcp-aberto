import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools.collisions import find_collisions
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
ONE = "11111111-1111-1111-1111-111111111111"
TWO = "22222222-2222-2222-2222-222222222222"


async def test_find_collisions_uses_exact_schema_and_explicit_port():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        result = await find_collisions(client, [ONE], [TWO], 0.002, True, 0.003, 19723)
    assert result["collisions"][0]["hasBodyCollision"] is True
    request = fake.tapir_requests[-1]
    assert request["command"] == "GetCollisions"
    assert request["parameters"]["settings"] == {
        "volumeTolerance": 0.002,
        "performSurfaceCheck": True,
        "surfaceTolerance": 0.003,
    }


@pytest.mark.parametrize(
    "first,second", [([], [TWO]), ([ONE], []), ([ONE] * 501, [TWO]), (["bad"], [TWO])]
)
async def test_find_collisions_rejects_bad_groups(first, second):
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as client:
        with pytest.raises((ValueError, TypeError)):
            await find_collisions(client, first, second, port=19723)


async def test_find_collisions_rejects_negative_tolerance():
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as client:
        with pytest.raises(ValueError):
            await find_collisions(client, [ONE], [TWO], volume_tolerance=-1, port=19723)
