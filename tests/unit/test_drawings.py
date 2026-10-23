"""create_drawings (Tapir 1.7.0 CreateDrawings), against the simulated Archicad."""

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import drawings
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
GROUND = "77777777-7777-4777-8777-000000000003"  # View Map view (StoryItem)
WORKSHEET = "88888888-8888-4888-8888-000000000003"  # Project Map viewpoint
LAYOUT_DB = "99999999-8888-4888-8888-000000000013"  # "Planta baixa"
PLAN = {"view": "ground floor", "layout": "Planta baixa", "position": {"x": 0.21, "y": 0.148}}


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


async def apply(c, items):
    tool = drawings.create_drawings
    preview = await tool(c, items, 19723)
    return preview, await tool(c, items, 19723, False, preview["confirmation_token"])


async def test_view_placed_and_found_on_layout():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(c, [PLAN | {"name": "Planta térreo", "angle": 0.0}])
    planned = preview["items"][0]
    assert (planned["view_name"], planned["layout_name"]) == ("Ground floor", "Planta baixa")
    request = next(r for r in fake.tapir_requests if r["command"] == "CreateDrawings")
    assert request["parameters"] == {
        "drawingsData": [
            {
                "navigatorItemId": {"guid": GROUND},
                "layoutDatabaseId": {"guid": LAYOUT_DB},
                "position": {"x": 0.21, "y": 0.148},
                "name": "Planta térreo",
                "angle": 0.0,
            }
        ]
    }
    item = result["items"][0]
    assert item["status"] == "verified"
    assert fake.layout_drawings[LAYOUT_DB] == [item["drawing_guid"]]


async def test_project_map_viewpoint_by_guid():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(c, [PLAN | {"view": WORKSHEET.lower()}])
    assert preview["items"][0]["view_type"] == "WorksheetDrawingItem"
    assert "name" not in preview["items"][0]["parameters"]
    assert result["items"][0]["status"] == "verified"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"view": "Architecture"}, "view 'Architecture' does not exist"),
        ({"view": "77777777-7777-4777-8777-000000000002"}, "FolderItem, which cannot"),
        ({"view": "Estudo de fachada"}, "does not exist"),  # Project Map only by GUID
        ({"layout": "A3 Paisagem"}, "layout 'A3 Paisagem' does not exist"),
        ({"layout": "88888888-8888-4888-8888-000000000012"}, "MasterLayoutItem"),
        ({"layout": "Prancha 99"}, "does not exist"),
    ],
)
async def test_preview_refuses_what_tapir_cannot_place(change, message):
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match=message):
            await drawings.create_drawings(c, [PLAN | change], 19723)
    assert "CreateDrawings" not in fake.tapir_calls


async def test_drawing_missing_from_layout_fails_verification():
    fake = FakeArchicad(19723, drawing_lost=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [PLAN])
    item = result["items"][0]
    assert item["status"] == "verification_failed"
    assert item["mismatches"] == ["not on the layout"]


async def test_item_error_isolated():
    fake = FakeArchicad(19723, create_errors={0: {"error": {"code": -1, "message": "No."}}})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [PLAN, PLAN | {"position": {"x": 0.5, "y": 0.1}}])
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]


@pytest.mark.parametrize(
    "bad",
    [
        PLAN | {"view": ""},
        PLAN | {"layout": " Planta baixa"},
        PLAN | {"position": {"x": 0.1}},
        PLAN | {"scale": 2},
    ],
)
def test_bad_input_is_refused(bad):
    with pytest.raises(ValidationError):
        drawings.DrawingCreate.model_validate(bad)


async def test_count_limits():
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as c:
        with pytest.raises(ValueError, match="between 1 and 20"):
            await drawings.create_drawings(c, [])


async def test_update_drawings_of_a_layout():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="no Drawings"):
            await drawings.update_drawings(c, ["Planta baixa"], 19723)
        fake.layout_drawings[LAYOUT_DB] = ["D2000000-0000-4000-8000-000000000002"]
        preview = await drawings.update_drawings(c, ["planta baixa"], 19723)
        result = await drawings.update_drawings(
            c, ["planta baixa"], 19723, False, preview["confirmation_token"]
        )
    assert preview["items"][0]["layout_name"] == "Planta baixa"
    assert fake.updated_drawings == ["D2000000-0000-4000-8000-000000000002"]
    assert result["items"][0]["status"] == "unverified"
    assert "no read-back" in result["verification_note"]


async def test_update_drawings_refused_by_tapir_is_failed():
    fake = FakeArchicad(19723, update_drawings_refused=True)
    fake.layout_drawings[LAYOUT_DB] = ["D2000000-0000-4000-8000-000000000002"]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await drawings.update_drawings(c, ["Planta baixa"], 19723)
        result = await drawings.update_drawings(
            c, ["Planta baixa"], 19723, False, preview["confirmation_token"]
        )
    assert result["items"][0]["status"] == "failed"
    assert result["items"][0]["error"]["message"] == "Failed to update drawings."
