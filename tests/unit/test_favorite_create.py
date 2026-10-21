"""Walls, slabs, columns and beams from a named favorite (Tapir 1.7.0 favoriteName)."""

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import write
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
STORIES = [{"index": 0, "name": "Térreo", "level": 0.0}]
WALL_FAVORITE = " PAREDE 15 - ALVENARIA"
FAVORITES = {
    "Wall": [WALL_FAVORITE],
    "Slab": ["LAJE 12"],
    "Column": ["PILAR 20X40"],
    "Beam": ["VIGA 15X40"],
}
SETTINGS = {
    WALL_FAVORITE: {
        "defaults": {"height": 2.8, "thickness": 0.15},
        "details": {"structureType": "Composite", "profileType": "Normal"},
    },
    "LAJE 12": {"defaults": {"thickness": 0.12}},
    "PILAR 20X40": {"defaults": {"width": 0.2, "depth": 0.4}, "details": {"profileId": None}},
    "VIGA 15X40": {"defaults": {"width": 0.15, "height": 0.4}},
}
SQUARE = [{"x": 0, "y": 0}, {"x": 4, "y": 0}, {"x": 4, "y": 3}, {"x": 0, "y": 3}]


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model():
    return FakeArchicad(
        19723,
        stories=[dict(s) for s in STORIES],
        favorites={k: list(v) for k, v in FAVORITES.items()},
        favorite_settings=SETTINGS,
    )


def sent(fake, command, key):
    return next(r for r in fake.tapir_requests if r["command"] == command)["parameters"][key]


async def apply(tool, c, items):
    preview = await tool(c, items, 19723)
    return preview, await tool(c, items, 19723, False, preview["confirmation_token"])


async def test_wall_from_favorite_keeps_its_size_and_structure():
    fake = model()
    wall = {
        "start": {"x": 0, "y": 0},
        "end": {"x": 4, "y": 0},
        "floor_index": 0,
        "favorite": "parede 15 - alvenaria",
    }
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(write.create_walls, c, [wall])
    assert preview["items"][0]["favorite"] == WALL_FAVORITE
    payload = sent(fake, "CreateWalls", "wallsData")[0]
    assert payload["favoriteName"] == WALL_FAVORITE
    for left_out in ("height", "thickness", "structureType", "offset", "zCoordinate"):
        assert left_out not in payload
    assert result["status"] == "verified", result["items"][0].get("mismatches")
    details = fake.details[result["items"][0]["element_guid"]]["details"]
    assert details["structureType"] == "Composite" and details["begThickness"] == 0.15


async def test_given_fields_override_the_favorite_and_are_checked():
    fake = model()
    wall = {
        "start": {"x": 0, "y": 0},
        "end": {"x": 4, "y": 0},
        "floor_index": 0,
        "height": 3.1,
        "favorite": WALL_FAVORITE,
    }
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(write.create_walls, c, [wall])
    assert sent(fake, "CreateWalls", "wallsData")[0]["height"] == 3.1
    assert result["status"] == "verified"
    assert fake.details[result["items"][0]["element_guid"]]["details"]["height"] == 3.1


async def test_slab_column_and_beam_from_favorites():
    fake = model()
    slab = {"outline": SQUARE, "floor_index": 0, "level": 0.0, "favorite": "LAJE 12"}
    column = {
        "origin": {"x": 1, "y": 1},
        "floor_index": 0,
        "base_level": 0.0,
        "favorite": "PILAR 20X40",
    }
    beam = {
        "start": {"x": 0, "y": 0},
        "end": {"x": 4, "y": 0},
        "floor_index": 0,
        "level": 2.8,
        "favorite": "VIGA 15X40",
    }
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, slabs = await apply(write.create_slabs, c, [slab])
        _, columns = await apply(write.create_columns, c, [column])
        _, beams = await apply(write.create_beams, c, [beam])
    assert [r["status"] for r in (slabs, columns, beams)] == ["verified"] * 3
    assert "thickness" not in sent(fake, "CreateSlabs", "slabsData")[0]
    column_payload = sent(fake, "CreateColumns", "columnsData")[0]
    assert not {"height", "width", "depth", "circleBased"} & set(column_payload)
    assert column_payload["coreAnchor"] == "Center"
    assert not {"width", "height", "circleBased"} & set(sent(fake, "CreateBeams", "beamsData")[0])


async def test_column_with_favorite_and_its_own_section():
    fake = model()
    column = {
        "origin": {"x": 1, "y": 1},
        "floor_index": 0,
        "base_level": 0.0,
        "width": 0.25,
        "depth": 0.25,
        "favorite": "PILAR 20X40",
    }
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(write.create_columns, c, [column])
    payload = sent(fake, "CreateColumns", "columnsData")[0]
    assert payload["width"] == 0.25 and payload["circleBased"] is False
    assert result["status"] == "verified"


async def test_unknown_or_wrong_type_favorite_refused_in_preview():
    fake = model()
    wall = {"start": {"x": 0, "y": 0}, "end": {"x": 4, "y": 0}, "floor_index": 0}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="No Wall favorite named 'LAJE 12'"):
            await write.create_walls(c, [{**wall, "favorite": "LAJE 12"}], 19723)
    assert "CreateWalls" not in fake.tapir_calls


@pytest.mark.parametrize(
    ("tool", "item"),
    [
        (
            write.create_walls,
            {"start": {"x": 0, "y": 0}, "end": {"x": 4, "y": 0}, "floor_index": 0},
        ),
        (write.create_slabs, {"outline": SQUARE, "floor_index": 0, "level": 0.0}),
        (write.create_columns, {"origin": {"x": 1, "y": 1}, "floor_index": 0, "base_level": 0}),
        (
            write.create_walls,
            {
                "start": {"x": 0, "y": 0},
                "end": {"x": 4, "y": 0},
                "floor_index": 0,
                "favorite": "  ",
            },
        ),
    ],
)
async def test_size_required_without_a_favorite(tool, item):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValidationError):
            await tool(c, [item], 19723)
    assert not fake.calls
