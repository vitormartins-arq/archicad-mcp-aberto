"""create_classification_systems (Tapir 1.7.0), against the simulated Archicad."""

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import classification_systems as systems
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
LAB = {
    "name": "LAB Classificação",
    "version": "2026",
    "source": "https://lab.example",
    "date": "2026-10-23",
    "items": [
        {"id": "01", "name": "Vedações", "children": [
            {"id": "01.01", "name": "Alvenaria"},
            {"id": "01.02", "name": "Drywall", "description": "Gesso acartonado"},
        ]},
        {"id": "02", "name": "Estrutura"},
    ],
}  # fmt: skip


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


async def apply(c, items):
    preview = await systems.create_classification_systems(c, items, 19723)
    return preview, await systems.create_classification_systems(
        c, items, 19723, False, preview["confirmation_token"]
    )


async def test_system_and_tree_created_and_read_back():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(c, [LAB])
    assert preview["items"][0]["item_count"] == 4
    request = next(r for r in fake.tapir_requests if r["command"] == "CreateClassificationSystems")
    sent = request["parameters"]["classificationSystemsWithItems"][0]
    assert sent["classificationSystem"] == {
        "name": "LAB Classificação",
        "description": "",
        "source": "https://lab.example",
        "version": "2026",
        "date": "2026-10-23",
    }
    assert sent["classificationItems"][0]["children"][1] == {
        "id": "01.02",
        "name": "Drywall",
        "description": "Gesso acartonado",
    }
    assert result["status"] == "verified"
    assert result["items"][0]["system_guid"] in fake.classification_data["items"]


async def test_dropped_children_are_caught():
    fake = FakeArchicad(19723, classification_children_dropped=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [LAB])
    assert result["items"][0]["status"] == "verification_failed"
    assert result["items"][0]["mismatches"] == ["items"]


async def test_existing_name_and_version_is_refused():
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as c:
        with pytest.raises(ValueError, match="already exists"):
            await systems.create_classification_systems(
                c, [{**LAB, "name": "uniclass", "version": "2015"}], 19723
            )
        with pytest.raises(ValueError, match="appear twice"):
            await systems.create_classification_systems(c, [LAB, LAB], 19723)


def test_bad_trees_are_refused():
    for bad in (
        {**LAB, "items": []},
        {**LAB, "items": [{"id": "01", "name": "A"}, {"id": "01", "name": "B"}]},
        {**LAB, "name": " LAB"},
        {**LAB, "date": "23/10/2026"},
    ):
        with pytest.raises(ValidationError):
            systems.SystemCreate.model_validate(bad)
