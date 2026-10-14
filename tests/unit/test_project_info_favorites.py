import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import favorites, project_info
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
WALL = "11111111-1111-4111-8111-111111111111"
SLAB = "22222222-2222-4222-8222-222222222222"
MISSING = "99999999-9999-4999-8999-999999999999"


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
        favorites={"Wall": ["Parede 15", "Parede 25"], "Slab": ["Laje 12"]},
        layers={1: "Walls", 7: "Paredes"},
        **kwargs,
    )


async def apply(tool, c, inputs):
    preview = await tool(c, inputs, 19723)
    return await tool(c, inputs, 19723, False, preview["confirmation_token"])


def value(fake, key):
    return next(r["projectInfoValue"] for r in fake.project_info if r["projectInfoId"] == key)


async def test_read_project_info_fields():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await project_info.get_project_info_fields(c, 19723)
    assert result["total"] == 4
    assert result["fields"][0] == {
        "projectInfoId": "PROJECTNAME",
        "projectInfoName": "Nome do Projeto",
        "projectInfoValue": "Projeto teste",
    }


async def test_set_project_info_by_id_and_name():
    fake = model()
    changes = [
        {"field": "PROJECTNAME", "value": "Casa Silva"},
        {"field": "nome do cliente", "value": "Ana Silva"},
        {"field": "Cidade", "value": ""},
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await project_info.set_project_info_fields(c, changes, 19723)
        assert "SetProjectInfoField" not in fake.tapir_calls
        first, second, third = preview["items"]
        assert first["before"] == "Projeto teste" and not first["unchanged"]
        assert second["field_id"] == "CLIENT_NAME"
        assert third["unchanged"]
        token = preview["confirmation_token"]
        result = await project_info.set_project_info_fields(c, changes, 19723, False, token)
        with pytest.raises(ValueError, match="consumed"):
            await project_info.set_project_info_fields(c, changes, 19723, False, token)
    assert result["status"] == "verified"
    assert value(fake, "PROJECTNAME") == "Casa Silva" and value(fake, "CLIENT_NAME") == "Ana Silva"
    assert fake.tapir_calls.count("SetProjectInfoField") == 3


async def test_project_info_refusals():
    fake = model()
    fake.project_info.append(
        {"projectInfoId": "SITE_X", "projectInfoName": "Cidade", "projectInfoValue": ""}
    )
    fake.project_info.append(
        {
            "projectInfoId": "CLIENT_FULLNAME",
            "projectInfoName": "Nome Completo do Cliente",
            "projectInfoValue": "",
        }
    )
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="CLIENT_GIVENNAME"):
            await project_info.set_project_info_fields(
                c, [{"field": "Nome Completo do Cliente", "value": "Cliente Teste"}]
            )
        with pytest.raises(ValueError, match="does not exist"):
            await project_info.set_project_info_fields(c, [{"field": "Arquiteto", "value": "V"}])
        with pytest.raises(ValueError, match="ambiguous"):
            await project_info.set_project_info_fields(c, [{"field": "cidade", "value": "X"}])
        with pytest.raises(ValueError, match="twice"):
            await project_info.set_project_info_fields(
                c,
                [
                    {"field": "PROJECTNAME", "value": "A"},
                    {"field": "Nome do Projeto", "value": "B"},
                ],
            )
        for bad in (
            [],
            [{"field": "PROJECTNAME", "value": "A"}] * 31,
            [{"field": "", "value": "A"}],
        ):
            with pytest.raises(ValueError):
                await project_info.set_project_info_fields(c, bad)
    assert "SetProjectInfoField" not in fake.tapir_calls


async def test_project_info_failed_ignored_and_lost():
    fake = model(project_info_refused={"PROJECTNAME"})
    changes = [
        {"field": "PROJECTNAME", "value": "A"},
        {"field": "CLIENT_NAME", "value": "B"},
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(project_info.set_project_info_fields, c, changes)
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]
    assert result["items"][0]["error"]["message"] == "Failed to set project information field."
    fake = model(project_info_ignored=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(project_info.set_project_info_fields, c, changes[:1])
    assert result["items"][0]["status"] == "verification_failed"
    fake = model(lose_project_info_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(project_info.set_project_info_fields, c, changes)
    assert [i["status"] for i in result["items"]] == ["unknown", "unknown"]
    assert fake.tapir_calls.count("SetProjectInfoField") == 1


async def test_list_favorites():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await favorites.list_favorites(c, "Wall", 19723)
    assert result["favorites"] == ["Parede 15", "Parede 25"] and result["total"] == 2


async def test_apply_favorites_preview_then_apply():
    fake = model(favorite_layers={"Parede 25": 7})
    changes = [
        {"element_guid": WALL.lower(), "favorite": "parede 25"},
        {"element_guid": SLAB, "favorite": "Laje 12"},
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await favorites.apply_favorites(c, changes, 19723)
        assert "ApplyFavoritesToElements" not in fake.tapir_calls
        assert preview["items"][0]["favorite"] == "Parede 25"
        assert preview["items"][0]["layerName"] == "Walls"
        result = await favorites.apply_favorites(
            c, changes, 19723, False, preview["confirmation_token"]
        )
    assert [i["status"] for i in result["items"]] == ["unverified", "unverified"]
    assert result["status"] == "needs_review"
    assert result["items"][0]["after"] == {"type": "Wall", "floorIndex": 0, "layerIndex": 7}
    assert fake.applied_favorites == {WALL: ["Parede 25"], SLAB: ["Laje 12"]}
    request = next(r for r in fake.tapir_requests if r["command"] == "ApplyFavoritesToElements")
    assert request["parameters"] == {
        "favoritesToApply": [
            {"elementId": {"guid": WALL}, "favorite": "Parede 25"},
            {"elementId": {"guid": SLAB}, "favorite": "Laje 12"},
        ]
    }


async def test_apply_favorites_refusals():
    fake = model(locked_elements={SLAB})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="Wall favorite 'Laje 12' does not exist"):
            await favorites.apply_favorites(c, [{"element_guid": WALL, "favorite": "Laje 12"}])
        with pytest.raises(ValueError, match="Locked"):
            await favorites.apply_favorites(c, [{"element_guid": SLAB, "favorite": "Laje 12"}])
        with pytest.raises(ValueError, match="does not exist"):
            await favorites.apply_favorites(c, [{"element_guid": MISSING, "favorite": "Laje 12"}])
        with pytest.raises(ValueError, match="only once"):
            await favorites.apply_favorites(
                c,
                [
                    {"element_guid": WALL, "favorite": "Parede 15"},
                    {"element_guid": WALL.lower(), "favorite": "Parede 25"},
                ],
            )
    fake = model()
    fake.favorites["Wall"] = ["Parede", "PAREDE"]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="ambiguous"):
            await favorites.apply_favorites(c, [{"element_guid": WALL, "favorite": "parede"}])
        exact = await favorites.apply_favorites(c, [{"element_guid": WALL, "favorite": "PAREDE"}])
    assert exact["items"][0]["favorite"] == "PAREDE"
    assert "ApplyFavoritesToElements" not in fake.tapir_calls


async def test_apply_favorites_failed_and_lost():
    fake = model()
    changes = [
        {"element_guid": WALL, "favorite": "Parede 15"},
        {"element_guid": SLAB, "favorite": "Laje 12"},
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await favorites.apply_favorites(c, changes, 19723)
        original = fake._tapir

        def removed(params):
            if params["addOnCommandId"]["commandName"] == "ApplyFavoritesToElements":
                fake.favorites["Slab"] = []  # gone in Archicad at apply time
            return original(params)

        fake._tapir = removed
        result = await favorites.apply_favorites(
            c, changes, 19723, False, preview["confirmation_token"]
        )
    assert [i["status"] for i in result["items"]] == ["unverified", "failed"]
    fake = model(lose_favorite_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(favorites.apply_favorites, c, changes[:1])
        preview = await favorites.apply_favorites(c, changes[1:])
        with pytest.raises(ValueError, match="explicit port"):
            await favorites.apply_favorites(
                c, changes[1:], None, False, preview["confirmation_token"]
            )
    assert result["items"][0]["status"] == "unknown"
    assert fake.tapir_calls.count("ApplyFavoritesToElements") == 1


async def test_apply_favorite_with_leading_space():
    # Live AC30 build 3001 BRA (14/10/2026): the "- Default" favorites start with a space.
    name = " Parede Genérica - Default"
    fake = model()
    fake.favorites["Wall"].append(name)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        for typed in (name, "parede genérica - default"):
            preview = await favorites.apply_favorites(
                c, [{"element_guid": WALL, "favorite": typed}]
            )
            assert preview["items"][0]["favorite"] == name
        result = await apply(
            favorites.apply_favorites, c, [{"element_guid": WALL, "favorite": name}]
        )
    assert result["items"][0]["status"] == "unverified"
    assert fake.applied_favorites == {WALL: [name]}
