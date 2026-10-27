"""Walls, slabs, columns and beams from a named favorite (Tapir 1.7.0 favoriteName)."""

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.connection.errors import TapirError
from archicad_mcp_aberto.tools import drafting, labels, meshes, texts, write
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


async def test_wall_from_favorite_needs_height_and_thickness():
    # Tapir 1.7.0 CreateWalls refused a wall with only a favorite (live, 21/10/2026).
    wall = {
        "start": {"x": 0, "y": 0},
        "end": {"x": 4, "y": 0},
        "floor_index": 0,
        "favorite": WALL_FAVORITE,
    }
    with pytest.raises(ValidationError, match="height"):
        write.WallCreate.model_validate(wall)
    with pytest.raises(ValidationError, match="thickness required unless a composite"):
        write.WallCreate.model_validate({**wall, "height": 3.0})


async def test_wall_from_favorite_is_basic_with_the_given_size():
    fake = model()
    wall = {
        "start": {"x": 0, "y": 0},
        "end": {"x": 4, "y": 0},
        "floor_index": 0,
        "height": 3.1,
        "thickness": 0.05,
        "favorite": "parede 15 - alvenaria",
    }
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(write.create_walls, c, [wall])
    assert preview["items"][0]["favorite"] == WALL_FAVORITE
    assert "pass composite" in preview["items"][0]["note"]
    payload = sent(fake, "CreateWalls", "wallsData")[0]
    assert payload["favoriteName"] == WALL_FAVORITE and "structureType" not in payload
    assert payload["height"] == 3.1 and payload["thickness"] == 0.05
    assert result["status"] == "verified", result["items"][0].get("mismatches")
    details = fake.details[result["items"][0]["element_guid"]]["details"]
    # The favorite's composite is lost, as seen live: the wall comes out Basic.
    assert details["structureType"] == "Basic" and details["begThickness"] == 0.05


async def test_wall_with_composite_takes_its_thickness():
    fake = model()
    wall = {
        "start": {"x": 0, "y": 0},
        "end": {"x": 4, "y": 0},
        "floor_index": 0,
        "height": 3.0,
        "composite": "alvenaria 14cm com reboco",
        "favorite": WALL_FAVORITE,
    }
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(write.create_walls, c, [wall])
    assert "note" not in preview["items"][0]
    payload = sent(fake, "CreateWalls", "wallsData")[0]
    guid = "C0C0C0C0-0000-4000-8000-000000000001"
    assert payload["structureType"] == "Composite"
    assert payload["compositeId"] == {"guid": guid}
    assert payload["thickness"] == pytest.approx(0.14)
    assert result["status"] == "verified", result["items"][0].get("mismatches")
    details = fake.details[result["items"][0]["element_guid"]]["details"]
    assert details["structureType"] == "Composite" and details["compositeId"]["guid"] == guid


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"composite": "Nada"}, "Composite 'Nada' does not exist"),
        ({"composite": "Laje Composta 20"}, "is not for walls"),
        ({"composite": "Alvenaria 14cm com Reboco", "thickness": 0.2}, "is 0.14 m thick"),
    ],
)
async def test_bad_wall_composite_refused_in_preview(extra, message):
    fake = model()
    wall = {"start": {"x": 0, "y": 0}, "end": {"x": 4, "y": 0}, "floor_index": 0}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match=message):
            await write.create_walls(c, [{**wall, "height": 3.0, **extra}], 19723)
    assert "CreateWalls" not in fake.tapir_calls


async def test_wall_without_height_is_refused_by_the_fake_like_tapir():
    fake = model()
    wall = {"begCoordinate": {"x": 0, "y": 0}, "endCoordinate": {"x": 1, "y": 0}}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(TapirError) as caught:
            await c.tapir(19723, "CreateWalls", {"wallsData": [wall]})
    assert "Invalid command parameters" in str(caught.value.detail)
    assert not fake.details


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
    wall = {
        "start": {"x": 0, "y": 0},
        "end": {"x": 4, "y": 0},
        "floor_index": 0,
        "height": 3.0,
        "thickness": 0.2,
    }
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


SECOND = [
    (
        "Zone",
        write.create_zones,
        "CreateZones",
        "zonesData",
        {"outline": SQUARE, "name": "SALA", "number": "01", "floor_index": 0},
    ),
    (
        "Line",
        drafting.create_lines,
        "CreateLineElements",
        "linesData",
        {"start": {"x": 0, "y": 0}, "end": {"x": 5, "y": 0}, "floor_index": 0},
    ),
    (
        "Hatch",
        drafting.create_fills,
        "CreateHatches",
        "hatchesData",
        {"outline": SQUARE, "floor_index": 0},
    ),
    (
        "Text",
        texts.create_texts,
        "CreateTexts",
        "textsData",
        {"text": "SALA", "position": {"x": 1, "y": 1}, "floor_index": 0},
    ),
    (
        "Label",
        labels.create_labels,
        "CreateLabels",
        "labelsData",
        {"text": "NOTA", "position": {"x": 1, "y": 1}, "floor_index": 0},
    ),
    (
        "Mesh",
        meshes.create_meshes,
        "CreateMeshes",
        "meshesData",
        {
            "outline": [{**p, "z": 0.0} for p in SQUARE],
            "floor_index": 0,
            "level": 0.0,
        },
    ),
]


@pytest.mark.parametrize(("kind", "tool", "command", "key", "item"), SECOND)
async def test_other_create_tools_take_a_favorite(kind, tool, command, key, item):
    fake = model()
    fake.favorites[kind] = [f" {kind.upper()} LAB"]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match=f"No {kind} favorite"):
            await tool(c, [{**item, "favorite": "OUTRO"}], 19723)
        preview, result = await apply(tool, c, [{**item, "favorite": f"{kind.lower()} lab"}])
    assert preview["items"][0]["favorite"] == f" {kind.upper()} LAB"
    assert sent(fake, command, key)[0]["favoriteName"] == f" {kind.upper()} LAB"
    assert result["status"] == "verified", result["items"][0].get("mismatches")


async def test_mesh_settings_come_from_the_favorite_unless_given():
    fake = model()
    fake.favorites["Mesh"] = ["TERRENO LAB"]
    mesh = {
        "outline": [{**p, "z": 0.0} for p in SQUARE],
        "floor_index": 0,
        "level": 0.0,
        "favorite": "TERRENO LAB",
        "ridges": "AllSmooth",
    }
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        await apply(meshes.create_meshes, c, [mesh])
    payload = sent(fake, "CreateMeshes", "meshesData")[0]
    assert payload["ridges"] == "AllSmooth"
    assert not {"skirtType", "skirtLevel", "showLines"} & set(payload)


async def test_object_from_favorite_keeps_its_angle_and_notes_the_library_part():
    fake = FakeArchicad(
        19723,
        stories=[dict(s) for s in STORIES],
        favorites={"Object": ["CADEIRA LAB"]},
        favorite_settings={"CADEIRA LAB": {"defaults": {"angle": 1.5}}},
    )
    fake.library_parts = {"Cadeira 01"}
    item = {
        "library_part_name": "Cadeira 01",
        "origin": {"x": 1, "y": 2},
        "floor_index": 0,
        "base_level": 0.0,
        "favorite": "cadeira lab",
    }
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(write.create_objects, c, [item])
    assert "library part" in preview["items"][0]["note"]
    payload = sent(fake, "CreateObjects", "objectsData")[0]
    assert payload["favoriteName"] == "CADEIRA LAB" and "angle" not in payload
    assert result["items"][0]["status"] == "verified"
    assert fake.details[result["items"][0]["element_guid"]]["details"]["angle"] == 1.5


async def test_object_favorite_of_another_type_fails_that_object():
    fake = FakeArchicad(
        19723, stories=[dict(s) for s in STORIES], favorites={"Object": ["CADEIRA LAB"]}
    )
    fake.library_parts = {"Cadeira 01"}
    item = {
        "library_part_name": "Cadeira 01",
        "origin": {"x": 1, "y": 2},
        "floor_index": 0,
        "base_level": 0.0,
        "favorite": "PAREDE",
    }
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="No Object favorite named 'PAREDE'"):
            await write.create_objects(c, [item], 19723)
