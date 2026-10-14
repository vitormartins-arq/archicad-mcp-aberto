from copy import deepcopy

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import renames
from tests.unit.fake_archicad import (
    FakeArchicad,
    combination_guid,
    fake_transport,
    folder_guid,
    layer_guid,
)

pytestmark = pytest.mark.anyio
VIEW_MAP = {
    "navigatorItemId": {"guid": "99999999-0000-4000-8000-000000000001"},
    "type": "ProjectItem",
    "name": "Mapa de Vistas",
    "children": [
        {
            "navigatorItem": {
                "navigatorItemId": {"guid": "99999999-0000-4000-8000-000000000002"},
                "type": "FolderItem",
                "name": "01 ANT - Plantas",
                "children": [
                    {
                        "navigatorItem": {
                            "navigatorItemId": {"guid": "99999999-0000-4000-8000-000000000003"},
                            "type": "StoryItem",
                            "name": "ANT - Térreo",
                        }
                    }
                ],
            }
        },
        {
            "navigatorItem": {
                "navigatorItemId": {"guid": "99999999-0000-4000-8000-000000000004"},
                "type": "StoryItem",
                "name": "ANT - Térreo",
            }
        },
    ],
}


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    fake = FakeArchicad(
        19723, layers={1: "ANT - Parede", 2: "ANT - Laje", 3: "EST - Viga"}, **kwargs
    )
    fake.navigator_trees["PublicViewMap"] = deepcopy(VIEW_MAP)
    return fake


async def apply(c, **request):
    preview = await renames.rename_items(c, port=19723, **request)
    result = await renames.rename_items(
        c, port=19723, dry_run=False, confirmation_token=preview["confirmation_token"], **request
    )
    return preview, result


def nav_names(fake):
    return [n["name"] for n in fake._nav_items("PublicViewMap")]


async def test_view_map_find_and_replace():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(c, kind="view_map", find="ANT - ", replace="ARQ - ")
    assert "RenameNavigatorItem" in fake.tapir_calls
    assert [i["after_name"]["name"] for i in preview["items"]] == [
        "01 ARQ - Plantas",
        "ARQ - Térreo",
        "ARQ - Térreo",
    ]
    assert result["status"] == "verified"
    assert nav_names(fake) == ["Mapa de Vistas", "01 ARQ - Plantas", "ARQ - Térreo", "ARQ - Térreo"]
    assert fake.tapir_calls.count("RenameNavigatorItem") == 3


async def test_preview_does_not_rename_and_token_is_single_use():
    fake = model()
    request = {"kind": "layers", "renames": [{"old": "EST - Viga", "new": "EST - Vigas"}]}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await renames.rename_items(c, port=19723, **request)
        assert fake.layers[3] == "EST - Viga"
        token = preview["confirmation_token"]
        result = await renames.rename_items(
            c, port=19723, dry_run=False, confirmation_token=token, **request
        )
        with pytest.raises(ValueError, match="consumed"):
            await renames.rename_items(
                c, port=19723, dry_run=False, confirmation_token=token, **request
            )
    assert result["status"] == "verified" and fake.layers[3] == "EST - Vigas"
    sent = next(r for r in fake.tapir_requests if r["command"] == "CreateLayers")["parameters"]
    assert sent == {
        "layerDataArray": [{"attributeId": {"guid": layer_guid(3)}, "name": "EST - Vigas"}],
        "overwriteExisting": True,
    }


async def test_attributes_favorites_and_property_kinds():
    fake = model()
    fake.favorites["Wall"] = [" Parede Genérica - Default", "ANT Alvenaria 14"]
    material = "46464646-4646-4646-8646-000000000001"
    fake.building_materials[material] = {
        "attributeId": {"guid": material},
        "index": 1,
        "name": "ANT Concreto",
    }
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, materials = await apply(c, kind="building_materials", find="ANT ", replace="ARQ ")
        _, favorites = await apply(c, kind="favorites", find="ANT ", replace="ARQ ")
        _, groups = await apply(c, kind="property_groups", find="Projeto", replace="Obra")
        _, props = await apply(
            c, kind="properties", renames=[{"old": "Fase", "new": "Etapa"}], scope="obra"
        )
    assert [r["status"] for r in (materials, favorites, groups, props)] == ["verified"] * 4
    assert fake.building_materials[material]["name"] == "ARQ Concreto"
    assert fake.favorites["Wall"] == [" Parede Genérica - Default", "ARQ Alvenaria 14"]
    assert [g["name"] for g in fake.property_groups] == ["Geral", "Obra"]  # built-in kept
    assert fake.custom_properties[0]["propertyName"] == "Etapa"


async def test_classification_items_rename_id_and_name():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(
            c,
            kind="classification_items",
            find="Parede",
            replace="Vedação",
            scope="ARCHICAD Classification",
        )
        _, systems = await apply(
            c,
            kind="classification_systems",
            renames=[{"old": "Uniclass", "new": "Uniclass 2015"}],
        )
    item = preview["items"][0]
    assert item["before"] == {"id": "Parede", "name": "Parede"}
    assert item["parameters"]["id"] == "Vedação" and item["parameters"]["name"] == "Vedação"
    assert result["status"] == "verified" and systems["status"] == "verified"


async def test_refusals_before_any_rename():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        cases = [
            ({"kind": "layers", "find": "XYZ", "replace": "A"}, "nothing to rename"),
            ({"kind": "layers", "renames": [{"old": "Nada", "new": "A"}]}, "No layers named"),
            ({"kind": "layers", "find": "ANT - Laje", "replace": "ANT - Parede"}, "Two layers"),
            ({"kind": "layers", "find": "ANT - Laje", "replace": " "}, "blank"),
            ({"kind": "favorites", "find": "A", "replace": "B", "scope": "Nada"}, "not supported"),
        ]
        for request, message in cases:
            with pytest.raises(ValueError, match=message):
                await renames.rename_items(c, **request)
        for bad in (
            {"kind": "layers"},
            {"kind": "layers", "find": "A"},
            {"kind": "layers", "find": "A", "replace": "B", "renames": [{"old": "A", "new": "B"}]},
            {"kind": "layers", "renames": [{"old": "A", "new": "B"}, {"old": "A", "new": "C"}]},
            {"kind": "layers", "find": "A", "replace": "B", "scope": "x"},
            {"kind": "styles", "find": "A", "replace": "B"},
            {"kind": "surfaces", "find": "Pintura", "replace": "Tinta"},  # texture changed live
        ):
            with pytest.raises(ValidationError):
                await renames.rename_items(c, **bad)
    assert not {"CreateLayers", "RenameFavorites"} & set(fake.tapir_calls)


async def test_find_with_empty_replace_removes_the_text():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await renames.rename_items(c, "view_map", find="01 ", replace="")
    assert [i["after_name"]["name"] for i in preview["items"]] == ["ANT - Plantas"]


async def test_failed_ignored_and_lost():
    fake = model(rename_errors={0: {"code": -1, "message": "no"}})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, kind="layers", find="ANT - ", replace="ARQ - ")
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]
    fake = model(rename_ignored=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, kind="view_map", find="ANT", replace="ARQ")
    assert {i["status"] for i in result["items"]} == {"verification_failed"}
    fake = model(lose_rename_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, kind="view_map", find="ANT", replace="ARQ")
        preview = await renames.rename_items(c, "layers", find="ANT", replace="ARQ")
        with pytest.raises(ValueError, match="explicit port"):
            await renames.rename_items(
                c,
                "layers",
                find="ANT",
                replace="ARQ",
                dry_run=False,
                confirmation_token=preview["confirmation_token"],
            )
    assert [i["status"] for i in result["items"]] == ["unknown", "failed", "failed"]
    assert fake.tapir_calls.count("RenameNavigatorItem") == 1
    assert "Never retry" in result["warning"]


async def test_plan_changed_since_preview():
    fake = model()
    request = {"kind": "layers", "find": "ANT", "replace": "ARQ"}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await renames.rename_items(c, port=19723, **request)
        fake.layers[4] = "ANT - Forro"
        with pytest.raises(ValueError, match="changed since preview"):
            await renames.rename_items(
                c,
                port=19723,
                dry_run=False,
                confirmation_token=preview["confirmation_token"],
                **request,
            )
    assert "CreateLayers" not in fake.tapir_calls


async def test_layer_combinations_keep_layer_states():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(c, kind="layer_combinations", find="ETAPA", replace="FASE")
    assert result["status"] == "verified"
    assert [c["name"] for c in fake.layer_combinations.values()] == [
        "0ª FASE | (3D) ARCHICAD",
        "1ª FASE | CADASTRO",
    ]
    assert fake.layer_combinations[2]["layers"] == {1: {"isHidden": True}}
    sent = next(r for r in fake.tapir_requests if r["command"] == "CreateLayerCombinations")
    assert sent["parameters"]["layerCombinationDataArray"][0] == {
        "attributeId": {"guid": combination_guid(1)},
        "name": "0ª FASE | (3D) ARCHICAD",
        "layers": [],
    }
    assert len({i["layer_states"] for i in preview["items"]}) == 2


async def test_layer_combination_with_reset_states_fails_verification():
    fake = model(combination_reset_on_rename=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(
            c, kind="layer_combinations", renames=[{"old": "1ª ETAPA | CADASTRO", "new": "X"}]
        )
    (item,) = result["items"]
    assert item["status"] == "verification_failed" and item["mismatches"] == ["layer_states"]


async def test_attribute_folders():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(
            c,
            kind="attribute_folders",
            scope="layer",
            renames=[
                {"old": "ANOTAÇÃO", "new": "ANOTAÇÕES"},
                {"old": "ANT - Antigo", "new": "ANT"},
            ],
        )
        with pytest.raises(ValueError, match="start or end"):
            await renames.rename_items(
                c, "attribute_folders", find="ESTRUTURA", replace="ESTRUTURA ", scope="Layer"
            )
        with pytest.raises(ValueError, match="Two attribute_folders"):
            await renames.rename_items(
                c, "attribute_folders", find="ESTRUTURA", replace="ANOTAÇÕES", scope="Layer"
            )
        with pytest.raises(ValueError, match="No attribute_folders named"):
            await renames.rename_items(  # the root folder is not renamed
                c, "attribute_folders", renames=[{"old": "Camadas", "new": "X"}], scope="Layer"
            )
    assert result["status"] == "verified"
    assert [i["where"] for i in preview["items"]] == ["", "/ARQUITETURA"]
    request = next(r for r in fake.command_requests if r["command"] == "API.RenameAttributeFolders")
    assert request["parameters"]["attributeFolderParametersList"][0] == {
        "attributeFolderId": {"guid": folder_guid(1)},
        "newName": "ANOTAÇÕES",
    }
    root = fake.attribute_folders["Layer"]
    assert root["name"] == "Camadas"
    assert [f["attributeFolder"]["name"] for f in root["subfolders"]] == [
        "ANOTAÇÕES",
        "ARQUITETURA",
        "ESTRUTURA",
    ]
    for bad in (
        {"kind": "attribute_folders", "find": "A", "replace": "B"},
        {"kind": "attribute_folders", "find": "A", "replace": "B", "scope": "Wall"},
    ):
        with pytest.raises(ValidationError):
            await renames.rename_items(None, **bad)


async def test_attribute_folders_failed_and_lost():
    fake = model(rename_errors={1: {"code": -1, "message": "no"}})
    request = {"kind": "attribute_folders", "find": "A", "replace": "B", "scope": "Layer"}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, **request)
    assert [i["status"] for i in result["items"]] == ["verified", "failed", "verified", "verified"]
    fake = model(lose_rename_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, **request)
    assert {i["status"] for i in result["items"]} == {"unknown"}
    assert "Never retry" in result["warning"]


async def test_refused_call_is_failed_not_unknown():
    for kind in ("layers", "view_map"):
        fake = model(rename_call_refused=True)
        async with ArchicadClient(transport=fake_transport(fake)) as c:
            _, result = await apply(c, kind=kind, find="ANT", replace="ARQ")
        assert {i["status"] for i in result["items"]} == {"failed"}
        assert "warning" not in result
    assert fake.layers[1] == "ANT - Parede"
