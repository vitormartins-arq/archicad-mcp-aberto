import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import documents
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
MASTER = "88888888-8888-4888-8888-000000000012"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


async def apply(tool, c, inputs):
    preview = await tool(c, inputs, 19723)
    return await tool(c, inputs, 19723, False, preview["confirmation_token"])


def names(fake, map_id, kind):
    return [n["name"] for n in fake._nav_items(map_id) if n["type"] == kind]


async def test_create_worksheets_and_details():
    fake = FakeArchicad(19723)
    sheets = [{"name": "Rascunho", "reference_id": "W2"}, {"name": "Estudo", "reference_id": "W3"}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await documents.create_worksheets(c, sheets, 19723)
        assert "CreateWorksheets" not in fake.tapir_calls
        token = preview["confirmation_token"]
        result = await documents.create_worksheets(c, sheets, 19723, False, token)
        with pytest.raises(ValueError, match="consumed"):
            await documents.create_worksheets(c, sheets, 19723, False, token)
        detail = await apply(
            documents.create_details, c, [{"name": "Escada", "reference_id": "D1"}]
        )
    assert result["status"] == "verified" and detail["status"] == "verified"
    assert all(i["worksheet_receipt_id"] and i["navigator_guid"] for i in result["items"])
    assert names(fake, "ProjectMap", "WorksheetDrawingItem") == [
        "Estudo de fachada",
        "Rascunho",
        "Estudo",
    ]
    assert names(fake, "ProjectMap", "DetailDrawingItem") == ["Escada"]
    request = next(r for r in fake.tapir_requests if r["command"] == "CreateWorksheets")
    assert request["parameters"] == {
        "worksheetsData": [
            {"name": "Rascunho", "referenceId": "W2"},
            {"name": "Estudo", "referenceId": "W3"},
        ]
    }


async def test_create_layouts_by_master_id():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await documents.create_layouts(c, [{"name": "Cortes", "master": "a3 paisagem"}])
        assert preview["items"][0]["master_name"] == "A3 Paisagem"
        result = await apply(
            documents.create_layouts, c, [{"name": "Cortes", "master": "a3 paisagem"}]
        )
    assert result["status"] == "verified"
    assert names(fake, "LayoutBook", "LayoutItem") == ["Planta baixa", "Cortes"]
    request = next(r for r in fake.tapir_requests if r["command"] == "CreateLayout")
    assert request["parameters"] == {
        "layoutsData": [{"masterNavigatorItemId": {"guid": MASTER}, "layoutName": "Cortes"}]
    }


async def test_document_refusals():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="already exists"):
            await documents.create_worksheets(
                c, [{"name": "estudo de fachada", "reference_id": "w1"}]
            )
        with pytest.raises(ValueError, match="twice"):
            await documents.create_details(
                c,
                [{"name": "A", "reference_id": "D1"}, {"name": "a", "reference_id": "d1"}],
            )
        with pytest.raises(ValueError, match="does not exist"):
            await documents.create_layouts(c, [{"name": "X", "master": "A1"}])
        with pytest.raises(ValueError, match="already exists"):
            await documents.create_layouts(c, [{"name": "planta baixa", "master": "A3 Paisagem"}])
        with pytest.raises(ValueError, match="between 1 and 20"):
            await documents.create_worksheets(c, [{"name": "A", "reference_id": "W"}] * 21)
        for bad in (
            [{"name": "", "reference_id": "W"}],
            [{"name": " A", "reference_id": "W"}],
            [{"name": "A"}],
            [{"name": "A", "reference_id": "W", "x": 1}],
        ):
            with pytest.raises(ValidationError):
                await documents.create_worksheets(c, bad)
    master = next(n for n in fake._nav_items("LayoutBook") if n["type"] == "MasterLayoutItem")
    twin = {**master, "name": "A3 PAISAGEM", "navigatorItemId": {"guid": MASTER[:-1] + "9"}}
    fake.navigator_trees["LayoutBook"]["children"].append({"navigatorItem": twin})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="ambiguous"):
            await documents.create_layouts(c, [{"name": "X", "master": "a3 paisagem"}])
    assert not {"CreateWorksheets", "CreateDetails", "CreateLayout"} & set(fake.tapir_calls)


async def test_document_failed_mismatch_and_lost():
    error = {"error": {"code": -1, "message": "Failed to create worksheet database."}}
    sheets = [{"name": "A", "reference_id": "W2"}, {"name": "B", "reference_id": "W3"}]
    fake = FakeArchicad(19723, document_errors={0: error})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(documents.create_worksheets, c, sheets)
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]
    fake = FakeArchicad(19723, document_stored_name="Outro")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(documents.create_worksheets, c, sheets[:1])
    assert result["items"][0]["mismatches"] == ["name"]
    fake = FakeArchicad(19723, lose_document_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(documents.create_worksheets, c, sheets[:1])
        preview = await documents.create_worksheets(c, sheets[1:])
        with pytest.raises(ValueError, match="explicit port"):
            await documents.create_worksheets(
                c, sheets[1:], None, False, preview["confirmation_token"]
            )
    assert result["items"][0]["status"] == "unknown"
    assert fake.tapir_calls.count("CreateWorksheets") == 1


async def test_layout_master_removed_after_preview():
    fake = FakeArchicad(19723)
    layouts = [{"name": "Cortes", "master": "A3 Paisagem"}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await documents.create_layouts(c, layouts, 19723)
        fake.navigator_trees["LayoutBook"]["children"].pop(0)
        with pytest.raises(ValueError, match="does not exist"):
            await documents.create_layouts(c, layouts, 19723, False, preview["confirmation_token"])
    assert "CreateLayout" not in fake.tapir_calls
