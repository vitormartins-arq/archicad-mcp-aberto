"""create_zone_categories (Tapir 1.7.0 CreateZoneCategories), against the simulated Archicad."""

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import zone_categories
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
GREEN = {"red": 0.2, "green": 0.6, "blue": 0.3}


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    return FakeArchicad(19723, stories=[{"index": 0, "name": "Térreo", "level": 0.0}], **kwargs)


async def apply(c, items):
    tool = zone_categories.create_zone_categories
    preview = await tool(c, items, 19723)
    return preview, await tool(c, items, 19723, False, preview["confirmation_token"])


async def test_category_created_and_read_back():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(c, [{"name": "Jardim", "code": "JD", "color": GREEN}])
    assert preview["stamp_from"] == "Área"
    request = next(r for r in fake.tapir_requests if r["command"] == "CreateZoneCategories")
    assert request["parameters"] == {
        "zoneCategoryDataArray": [{"name": "Jardim", "categoryCode": "JD", "color": GREEN}],
        "overwriteExisting": False,
    }
    item = result["items"][0]
    assert item["status"] == "verified" and item["zone_category_guid"]


async def test_name_only_is_enough():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [{"name": "Depósito"}])
    request = next(r for r in fake.tapir_requests if r["command"] == "CreateZoneCategories")
    assert request["parameters"]["zoneCategoryDataArray"] == [{"name": "Depósito"}]
    assert result["items"][0]["status"] == "verified"


async def test_existing_or_repeated_name_refused_in_preview():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="already exists"):
            await zone_categories.create_zone_categories(c, [{"name": "área"}], 19723)
        with pytest.raises(ValueError, match="appears twice"):
            await zone_categories.create_zone_categories(
                c, [{"name": "Hall"}, {"name": "HALL"}], 19723
            )
    assert "CreateZoneCategories" not in [r["command"] for r in fake.tapir_requests]


async def test_other_code_stored_fails_verification():
    fake = model(zone_category_code_stored="XX")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [{"name": "Jardim", "code": "JD"}])
    item = result["items"][0]
    assert item["status"] == "verification_failed" and item["mismatches"] == ["categoryCode"]


async def test_refused_item_reported():
    fake = model(create_errors={0: {"error": {"code": -1, "message": "Failed to create."}}})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [{"name": "Jardim"}, {"name": "Hall"}])
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]


@pytest.mark.parametrize(
    "bad",
    [
        {"name": ""},
        {"name": " Jardim"},
        {"name": "Jardim", "color": {"red": 2, "green": 0, "blue": 0}},
        {"name": "Jardim", "color": {"red": 1, "green": 0}},
    ],
)
def test_invalid_input_refused(bad):
    with pytest.raises(ValidationError):
        zone_categories.ZoneCategoryCreate.model_validate(bad)


async def test_count_limits():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="between 1 and 50"):
            await zone_categories.create_zone_categories(c, [])
