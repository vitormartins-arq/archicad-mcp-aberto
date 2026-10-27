"""create_composites (Tapir 1.7.0 CreateComposites), against the simulated Archicad."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import composites
from tests.unit.fake_archicad import BUILDING_MATERIALS_FIXTURE, FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
CONCRETE = {"attributeId": {"guid": "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"}}
INSULATION = {"attributeId": {"guid": "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"}}
SOLID = {"attributeId": {"guid": "11E11E11-0000-4000-8000-000000000001"}}
DASHED = {"attributeId": {"guid": "11E11E11-0000-4000-8000-000000000002"}}
SANDWICH = {
    "name": "Parede Sanduíche 25",
    "use_with": ["Wall"],
    "skins": [
        {"building_material": "Structural concrete", "thickness": 0.1, "type": "Finish"},
        {"building_material": "insulation", "thickness": 0.05, "pen": 20, "type": "Other"},
        {"building_material": "Structural concrete", "thickness": 0.1},
    ],
}


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    materials = {
        row["attributeId"]["guid"]: deepcopy(row)
        for row in BUILDING_MATERIALS_FIXTURE["get_building_materials"]["buildingMaterials"]
    }
    return FakeArchicad(19723, building_materials=materials, **kwargs)


async def apply(c, items):
    tool = composites.create_composites
    preview = await tool(c, items, 19723)
    return preview, await tool(c, items, 19723, False, preview["confirmation_token"])


async def test_composite_created_and_read_back():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(c, [SANDWICH])
    planned = preview["items"][0]
    assert planned["total_thickness"] == 0.25
    assert planned["separator_line"] == "Linha Contínua"
    request = next(r for r in fake.tapir_requests if r["command"] == "CreateComposites")
    assert request["parameters"] == {
        "compositeDataArray": [
            {
                "name": "Parede Sanduíche 25",
                "useWith": ["Wall"],
                "skins": [
                    {"type": "Finish", "buildingMaterialId": CONCRETE, "framePen": 1,
                     "thickness": 0.1},
                    {"type": "Other", "buildingMaterialId": INSULATION, "framePen": 20,
                     "thickness": 0.05},
                    {"type": "Core", "buildingMaterialId": CONCRETE, "framePen": 1,
                     "thickness": 0.1},
                ],
                "separators": [{"lineTypeId": SOLID, "linePen": 1}] * 4,
            }
        ],
        "overwriteExisting": False,
    }  # fmt: skip
    item = result["items"][0]
    assert item["status"] == "verified" and item["composite_guid"]
    assert fake.composites[item["composite_guid"]]["name"] == "Parede Sanduíche 25"


async def test_separator_line_and_pen_by_name():
    fake = model()
    wanted = SANDWICH | {"name": "Laje 12", "use_with": ["Slab", "Roof"],
                         "separator_line": "tracejada", "separator_pen": 5}  # fmt: skip
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [wanted])
    request = next(r for r in fake.tapir_requests if r["command"] == "CreateComposites")
    separators = request["parameters"]["compositeDataArray"][0]["separators"]
    assert separators == [{"lineTypeId": DASHED, "linePen": 5}] * 4
    assert result["items"][0]["status"] == "verified"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"name": "alvenaria 14cm com reboco"}, "already exists"),
        ({"skins": [{"building_material": "Madeira", "thickness": 0.1}]}, "does not exist"),
        ({"separator_line": "Pontilhada"}, "does not exist"),
    ],
)
async def test_preview_refuses_bad_names(change, message):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match=message):
            await composites.create_composites(c, [SANDWICH | change], 19723)
    assert "CreateComposites" not in [r["command"] for r in fake.tapir_requests]


async def test_same_name_twice_is_refused():
    async with ArchicadClient(transport=fake_transport(model())) as c:
        with pytest.raises(ValueError, match="twice"):
            twice = [SANDWICH, SANDWICH | {"name": "parede sanduíche 25"}]
            await composites.create_composites(c, twice, 19723)


async def test_changed_thickness_fails_verification():
    fake = model(composite_thickness_stored=0.2)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [SANDWICH])
    item = result["items"][0]
    assert item["status"] == "verification_failed"
    assert item["mismatches"] == [f"skins[{n}].thickness" for n in range(3)]


async def test_item_error_isolated():
    fake = model(create_errors={0: {"error": {"code": -1, "message": "Failed to create."}}})
    second = SANDWICH | {"name": "Parede 2"}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [SANDWICH, second])
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]


@pytest.mark.parametrize(
    "bad",
    [
        SANDWICH | {"use_with": []},
        SANDWICH | {"use_with": ["Wall", "Wall"]},
        SANDWICH | {"use_with": ["Column"]},
        SANDWICH | {"skins": []},
        SANDWICH | {"skins": [{"building_material": "Insulation", "thickness": 0}]},
        SANDWICH | {"skins": [{"building_material": "Insulation", "thickness": 0.1, "pen": 0}]},
        SANDWICH | {"name": " Parede"},
        SANDWICH | {"separator_pen": 256},
    ],
)
def test_bad_input_is_refused(bad):
    with pytest.raises(ValidationError):
        composites.CompositeCreate.model_validate(bad)


async def test_count_limits():
    async with ArchicadClient(transport=fake_transport(model())) as c:
        with pytest.raises(ValueError, match="between 1 and 20"):
            await composites.create_composites(c, [])
