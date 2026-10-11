"""Building material reads use MockTransport only; fixtures are documentation-derived."""

from copy import deepcopy
from uuid import UUID

import pytest

from archicad_mcp_aberto.connection import AmbiguousTarget, ArchicadClient, CommandNotRegistered
from archicad_mcp_aberto.server import create_server
from archicad_mcp_aberto.tools.attributes import list_building_materials
from tests.unit.fake_archicad import BUILDING_MATERIALS_FIXTURE, FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
ROWS = BUILDING_MATERIALS_FIXTURE["get_building_materials"]["buildingMaterials"]
A, B = [row["attributeId"]["guid"] for row in ROWS]
UNKNOWN = "CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC"


def model(port=19723, **kwargs):
    return FakeArchicad(
        port,
        building_materials={row["attributeId"]["guid"]: deepcopy(row) for row in ROWS},
        **kwargs,
    )


def client(*instances):
    return ArchicadClient(ports=(19723, 19724), transport=fake_transport(*instances))


async def test_lists_guid_index_name_cut_fill_and_both_pens_without_mutation():
    fake = model()
    before = deepcopy(fake.building_materials)
    async with client(fake) as c:
        result = await list_building_materials(c)
    assert result == {
        "port": 19723,
        "total": 2,
        "buildingMaterials": [
            {
                "guid": A,
                "index": 1,
                "name": "Structural concrete",
                "cutFill": 15,
                "cutFillPen": 1,
                "cutFillBackgroundPen": 0,
            },
            {
                "guid": B,
                "index": 7,
                "name": "Insulation",
                "cutFill": 3,
                "cutFillPen": 20,
                "cutFillBackgroundPen": -1,
            },
        ],
    }
    assert fake.building_materials == before
    assert fake.elements == {} and fake.selection == []
    assert fake.tapir_calls == ["GetAttributesByType", "GetBuildingMaterials"]
    assert fake.tapir_requests[0]["parameters"] == {"attributeType": "BuildingMaterial"}
    assert fake.tapir_requests[1]["parameters"] == {
        "attributeIds": [{"attributeId": {"guid": A}}, {"attributeId": {"guid": B}}],
        "fields": ["cutFillIndex", "cutFillPen", "cutFillBackgroundPen"],
    }
    assert not any("Save" in command for command in fake.calls)


async def test_guid_filter_normalizes_deduplicates_and_preserves_order():
    fake = model()
    async with client(fake) as c:
        result = await list_building_materials(c, attribute_guids=[B.lower(), A, B])
    assert [row["guid"] for row in result["buildingMaterials"]] == [B, A]
    assert fake.tapir_calls == ["GetBuildingMaterials"]


async def test_unknown_guid_keeps_per_attribute_error_and_valid_results():
    fake = model()
    async with client(fake) as c:
        result = await list_building_materials(c, attribute_guids=[UNKNOWN, B])
    assert result["total"] == 2
    assert result["buildingMaterials"][0] == {
        "guid": UNKNOWN,
        "error": BUILDING_MATERIALS_FIXTURE["error"]["error"],
    }
    assert result["buildingMaterials"][1]["guid"] == B


@pytest.mark.parametrize("guids", [["not-a-guid"], [A, "bad"], [""], [None]])
async def test_invalid_guid_rejected_before_requests(guids):
    fake = model()
    async with client(fake) as c:
        with pytest.raises((ValueError, TypeError)):
            await list_building_materials(c, attribute_guids=guids)
    assert fake.calls == []


@pytest.mark.parametrize("filtered", [False, True])
async def test_empty_result_skips_details(filtered):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        result = await list_building_materials(c, attribute_guids=[] if filtered else None)
    assert result == {"port": 19723, "total": 0, "buildingMaterials": []}
    assert "GetBuildingMaterials" not in fake.tapir_calls


@pytest.mark.parametrize("guids", [None, [], [A]])
async def test_two_instances_without_port_are_refused(guids):
    first, second = model(), model(19724)
    async with client(first, second) as c:
        with pytest.raises(AmbiguousTarget):
            await list_building_materials(c, attribute_guids=guids)
    assert first.calls == second.calls == ["API.GetProductInfo"]
    assert first.tapir_calls == second.tapir_calls == []


async def test_explicit_port_uses_only_selected_project():
    first, second = model(), model(19724)
    second.building_materials[A]["name"] = "Other project concrete"
    async with client(first, second) as c:
        result = await list_building_materials(c, port=19724)
    assert result["port"] == 19724
    assert result["buildingMaterials"][0]["name"] == "Other project concrete"
    assert first.calls == []


async def test_missing_tapir_is_reported():
    fake = model(tapir_version=None)
    async with client(fake) as c:
        with pytest.raises(CommandNotRegistered):
            await list_building_materials(c, port=19723)


async def test_more_than_one_batch():
    fake = FakeArchicad(19723)
    for index in range(205):
        guid = str(UUID(int=index + 1)).upper()
        row = deepcopy(ROWS[0])
        row.update(attributeId={"guid": guid}, index=index + 1)
        fake.building_materials[guid] = row
    async with client(fake) as c:
        result = await list_building_materials(c)
    assert result["total"] == 205
    requests = [r for r in fake.tapir_requests if r["command"] == "GetBuildingMaterials"]
    assert [len(r["parameters"]["attributeIds"]) for r in requests] == [100, 100, 5]


@pytest.mark.parametrize("failure", ["cardinality", "guid"])
async def test_inconsistent_response_is_not_silently_associated(monkeypatch, failure):
    fake = model()
    async with client(fake) as c:
        original = c.tapir

        async def faulty(port, command, parameters=None, **kwargs):
            response = await original(port, command, parameters, **kwargs)
            if command == "GetBuildingMaterials":
                if failure == "cardinality":
                    response["buildingMaterials"].pop()
                else:
                    response["buildingMaterials"][0]["attributeId"]["guid"] = UNKNOWN
            return response

        monkeypatch.setattr(c, "tapir", faulty)
        with pytest.raises(ValueError):
            await list_building_materials(c)


async def test_mcp_registration_is_read_only():
    tool = next(
        t for t in await create_server().list_tools() if t.name == "list_building_materials"
    )
    assert tool.annotations.readOnlyHint and not tool.annotations.openWorldHint
    assert "attribute_guids" in tool.inputSchema["properties"]
    assert "port" in tool.inputSchema["properties"]


def test_fixture_explicitly_documents_provenance():
    assert BUILDING_MATERIALS_FIXTURE["provenance"]["live_capture"] is False
    assert BUILDING_MATERIALS_FIXTURE["provenance"]["kind"] == "documentation_and_source"
    assert len(BUILDING_MATERIALS_FIXTURE["provenance"]["sources"]) == 3
