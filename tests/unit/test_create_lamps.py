"""create_lamps (Tapir 1.7.0 CreateLamps), against the simulated Archicad."""

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import write
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
STORIES = [{"index": 0, "name": "Térreo", "level": 0.0}]


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def lamp(**changes):
    return {
        "library_part_name": "pendente 01",
        "origin": {"x": 1, "y": 2},
        "floor_index": 0,
        "base_level": 2.6,
        **changes,
    }


async def apply(c, items):
    preview = await write.create_lamps(c, items, 19723)
    return preview, await write.create_lamps(c, items, 19723, False, preview["confirmation_token"])


async def test_lamp_created_and_verified():
    fake = FakeArchicad(19723, stories=[dict(s) for s in STORIES])
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(c, [lamp(angle=0.5)])
    assert preview["items"][0]["library_part_guid"]
    request = next(r for r in fake.tapir_requests if r["command"] == "CreateLamps")
    assert request["parameters"]["lampsData"] == [
        {
            "libraryPartName": "pendente 01",
            "coordinates": {"x": 1.0, "y": 2.0, "z": 2.6},
            "floorIndex": 0,
            "angle": 0.5,
        }
    ]
    item = result["items"][0]
    assert item["status"] == "verified"
    assert fake.details[item["element_guid"]]["type"] == "Lamp"


async def test_object_part_is_not_a_lamp():
    fake = FakeArchicad(19723, stories=[dict(s) for s in STORIES])
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="not in loaded Lamp library parts"):
            await write.create_lamps(c, [lamp(library_part_name="Mesa Retangular 30")], 19723)
        with pytest.raises(ValueError, match="not in loaded Object library parts"):
            await write.create_objects(c, [lamp(library_part_name="Pendente 01")], 19723)


async def test_lamp_from_favorite():
    fake = FakeArchicad(
        19723,
        stories=[dict(s) for s in STORIES],
        favorites={"Lamp": ["PENDENTE LAB"]},
        favorite_settings={"PENDENTE LAB": {"defaults": {"angle": 1.0}}},
    )
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(c, [lamp(favorite="pendente lab")])
    request = next(r for r in fake.tapir_requests if r["command"] == "CreateLamps")
    payload = request["parameters"]["lampsData"][0]
    assert payload["favoriteName"] == "PENDENTE LAB" and "angle" not in payload
    assert "library part" in preview["items"][0]["note"]
    assert result["items"][0]["status"] == "verified"


async def test_count_limits():
    fake = FakeArchicad(19723, stories=[dict(s) for s in STORIES])
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="between 1 and 20 lamps"):
            await write.create_lamps(c, [])
