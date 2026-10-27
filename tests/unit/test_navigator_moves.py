"""move_navigator_items (Tapir 1.7.0 MoveNavigatorItem), against the simulated Archicad."""

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import layout_book, navigator, navigator_moves
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
ARCHITECTURE = "77777777-7777-4777-8777-000000000002"
SCHEDULE = "77777777-7777-4777-8777-000000000004"
LAYOUT = "88888888-8888-4888-8888-000000000013"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


async def apply(c, map_name, moves):
    tool = navigator_moves.move_navigator_items
    preview = await tool(c, map_name, moves, 19723)
    return preview, await tool(c, map_name, moves, 19723, False, preview["confirmation_token"])


async def test_view_moved_into_a_folder():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(
            c, "view_map", [{"item": "door schedule", "folder": "Architecture"}]
        )
        rows = {r["guid"]: r for r in await navigator._view_tree(c, 19723, "PublicViewMap")}
    assert preview["items"][0]["from_name"] == "Views"
    request = next(r for r in fake.tapir_requests if r["command"] == "MoveNavigatorItem")
    assert request["parameters"] == {
        "navigatorItemIdToMove": {"guid": SCHEDULE},
        "parentNavigatorItemId": {"guid": ARCHITECTURE},
    }
    assert result["status"] == "verified"
    assert rows[SCHEDULE]["parent_guid"] == ARCHITECTURE


async def test_layout_moved_into_a_subset():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        token = (await layout_book.create_layout_subsets(c, [{"name": "Executivo"}], 19723))[
            "confirmation_token"
        ]
        await layout_book.create_layout_subsets(c, [{"name": "Executivo"}], 19723, False, token)
        _, result = await apply(c, "layout_book", [{"item": LAYOUT, "folder": "Executivo"}])
    assert result["status"] == "verified"


async def test_ignored_move_is_caught():
    fake = FakeArchicad(19723, navigator_move_ignored=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, "view_map", [{"item": SCHEDULE, "folder": ARCHITECTURE}])
    assert result["items"][0]["mismatches"] == ["folder"]


async def test_preview_refusals():
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as c:
        tool = navigator_moves.move_navigator_items
        with pytest.raises(ValueError, match="already in"):
            await tool(c, "view_map", [{"item": "Ground floor", "folder": "Architecture"}], 19723)
        with pytest.raises(ValueError, match="inside itself"):
            await tool(c, "view_map", [{"item": "Architecture", "folder": "Architecture"}], 19723)
        with pytest.raises(ValueError, match="folder 'Views' does not exist"):
            await tool(c, "view_map", [{"item": "Door schedule", "folder": "Views"}], 19723)
        with pytest.raises(ValueError, match="item 'A3 Paisagem' does not exist"):
            await tool(c, "layout_book", [{"item": "A3 Paisagem", "folder": "Masters"}], 19723)
    with pytest.raises(ValidationError):
        navigator_moves.MoveRequest.model_validate({"map": "project_map", "moves": []})
