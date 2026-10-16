import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import favorites
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
WALL = "11111111-1111-4111-8111-111111111111"
SLAB = "22222222-2222-4222-8222-222222222222"
MISSING = "99999999-9999-4999-8999-999999999999"
create = favorites.create_favorites_from_elements


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    return FakeArchicad(
        19723,
        elements={WALL: "Wall", SLAB: "Slab"},
        details={
            WALL: {"type": "Wall", "floorIndex": 0, "layerIndex": 1, "details": {}},
            SLAB: {"type": "Slab", "floorIndex": 0, "layerIndex": 1, "details": {}},
        },
        favorites={"Wall": [" Parede 15"], "Slab": ["Laje 12"]},
        **kwargs,
    )


async def apply(c, inputs):
    preview = await create(c, inputs, 19723)
    return await create(c, inputs, 19723, False, preview["confirmation_token"])


async def test_preview_then_apply_reads_new_names_back():
    fake = model()
    inputs = [
        {"element_guid": WALL.lower(), "favorite": "Parede LAB 20", "folder": ["LAB", "Paredes"]},
        {"element_guid": SLAB, "favorite": "Laje LAB 15"},
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await create(c, inputs, 19723)
        assert "CreateFavoritesFromElements" not in fake.tapir_calls
        assert [i["elementType"] for i in preview["items"]] == ["Wall", "Slab"]
        result = await create(c, inputs, 19723, False, preview["confirmation_token"])
    assert fake.created_favorites == [
        {
            "elementId": {"guid": WALL},
            "favorite": "Parede LAB 20",
            "folder": ["LAB", "Paredes"],
        },
        {"elementId": {"guid": SLAB}, "favorite": "Laje LAB 15"},
    ]
    assert result["status"] == "verified"
    assert all(i["favorite_receipt_id"] for i in result["items"])
    assert fake.favorites["Wall"] == [" Parede 15", "Parede LAB 20"]
    assert fake.tapir_calls.count("CreateFavoritesFromElements") == 1


async def test_existing_or_repeated_name_and_missing_element_refused():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="already exists"):
            await create(c, [{"element_guid": WALL, "favorite": "parede 15"}], 19723)
        with pytest.raises(ValueError, match="appears twice"):
            await create(
                c,
                [
                    {"element_guid": WALL, "favorite": "Nova"},
                    {"element_guid": WALL, "favorite": "NOVA"},
                ],
                19723,
            )
        with pytest.raises(ValueError, match="does not exist"):
            await create(c, [{"element_guid": MISSING, "favorite": "X"}], 19723)
        # The same name for two different types is allowed: favorites are listed per type.
        preview = await create(
            c,
            [
                {"element_guid": WALL, "favorite": "Base"},
                {"element_guid": SLAB, "favorite": "Base"},
            ],
            19723,
        )
        assert len(preview["items"]) == 2
    assert "CreateFavoritesFromElements" not in fake.tapir_calls


@pytest.mark.parametrize(
    "item",
    [
        {"element_guid": "nope", "favorite": "X"},
        {"element_guid": WALL, "favorite": ""},
        {"element_guid": WALL, "favorite": " X"},
        {"element_guid": WALL, "favorite": "X", "folder": [""]},
        {"element_guid": WALL, "favorite": "X", "folder": ["a"] * 11},
        {"element_guid": WALL, "favorite": "X", "extra": 1},
    ],
)
async def test_invalid_inputs_refused_before_network(item):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await create(c, [item], 19723)
    assert fake.calls == []


async def test_refused_item_missing_name_and_lost_response():
    fake = model(favorite_create_refused={"Ruim"})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(
            c,
            [{"element_guid": WALL, "favorite": "Ruim"}, {"element_guid": SLAB, "favorite": "Boa"}],
        )
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]
    assert result["items"][0]["error"]["message"] == "Failed to create the favorite"
    fake = model(favorite_stored_name="Outro")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [{"element_guid": WALL, "favorite": "Nova"}])
    assert result["items"][0]["status"] == "verification_failed"
    assert result["items"][0]["mismatches"] == ["favorite_name"]
    fake = model(lose_favorite_create_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [{"element_guid": WALL, "favorite": "Nova"}])
    assert result["items"][0]["status"] == "unknown"
    assert fake.tapir_calls.count("CreateFavoritesFromElements") == 1


async def test_limits_and_explicit_port():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await create(c, [])
        with pytest.raises(ValueError):
            await create(c, [{"element_guid": WALL, "favorite": f"F{i}"} for i in range(51)])
        preview = await create(c, [{"element_guid": WALL, "favorite": "Nova"}])
        with pytest.raises(ValueError, match="explicit port"):
            await create(
                c,
                [{"element_guid": WALL, "favorite": "Nova"}],
                None,
                False,
                preview["confirmation_token"],
            )
