"""T22: Navigator reads from source-derived fake trees; no live Archicad."""

from copy import deepcopy
from uuid import UUID

import pytest

from archicad_mcp_aberto.connection import ArchicadClient, TapirError
from archicad_mcp_aberto.tools import navigator
from tests.unit.fake_archicad import NAVIGATOR_FIXTURE, FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio


async def test_project_map_preorder_and_hierarchy():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await navigator.get_navigator_tree(c, port=19723)
    rows = result["items"]
    assert result["navigator_map"] == "ProjectMap" and result["total"] == 3
    assert [r["type"] for r in rows] == ["ProjectItem", "StoryItem", "WorksheetDrawingItem"]
    assert rows[0]["parent_guid"] is None and rows[0]["depth"] == 0
    assert [r["parent_guid"] for r in rows[1:]] == [rows[0]["guid"]] * 2
    assert [r["depth"] for r in rows[1:]] == [1, 1]
    assert rows[1]["prefix"] == "0"
    assert rows[2]["uiId"] == "W1"
    assert fake.tapir_requests == [
        {"command": "GetNavigatorItemTree", "parameters": {"navigatorMapId": "ProjectMap"}}
    ]


async def test_layout_book_keeps_master_folder_and_layouts():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await navigator.get_navigator_tree(c, "LayoutBook", 19723)
    rows = result["items"]
    assert [r["type"] for r in rows] == [
        "BookItem",
        "MasterFolderItem",
        "MasterLayoutItem",
        "LayoutItem",
    ]
    assert rows[2]["parent_guid"] == rows[1]["guid"] and rows[2]["depth"] == 2
    assert rows[3]["parent_guid"] == rows[0]["guid"] and rows[3]["uiId"] == "A.01"


async def test_view_map_nested_preorder_and_guid_normalization():
    fake = FakeArchicad(19723)
    fake.navigator_trees["PublicViewMap"]["children"][0]["navigatorItem"]["navigatorItemId"][
        "guid"
    ] = "aabbccdd-abcd-4abc-8abc-0123456789ab"
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await navigator.get_navigator_tree(c, "PublicViewMap", 19723)
    rows = result["items"]
    assert [r["depth"] for r in rows] == [0, 1, 2, 1]
    assert rows[1]["guid"] == "AABBCCDD-ABCD-4ABC-8ABC-0123456789AB"
    assert rows[2]["parent_guid"] == rows[1]["guid"]
    assert rows[3]["name"] == "Door schedule"


@pytest.mark.parametrize(
    "query, expected",
    [("GROUND", "Ground floor"), ("scheduleitem", "Door schedule"), ("v.02", "Door schedule")],
)
async def test_query_matches_name_type_or_displayed_id_and_preserves_parent(query, expected):
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await navigator.get_navigator_tree(c, "PublicViewMap", 19723, query=query)
    assert result["total"] == 1 and result["items"][0]["name"] == expected
    assert result["items"][0]["parent_guid"] is not None
    assert result["items"][0]["depth"] >= 1


async def test_pagination_after_filtering_and_empty_match():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await navigator.get_navigator_tree(
            c, "PublicViewMap", 19723, query="item", offset=2, limit=1
        )
        empty = await navigator.get_navigator_tree(c, "PublicViewMap", 19723, query="not present")
        beyond = await navigator.get_navigator_tree(c, "PublicViewMap", 19723, offset=500)
    assert result["total"] == 4 and len(result["items"]) == 1
    assert result["items"][0]["name"] == "Ground floor"
    assert empty["total"] == 0 and empty["items"] == []
    assert beyond["total"] == 4 and beyond["items"] == []


async def test_publisher_set_default_is_one_set_and_exact_name_selects_another():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        first = await navigator.get_navigator_tree(c, "PublisherSets", 19723)
        named = await navigator.get_navigator_tree(
            c, "PublisherSets", 19723, publisher_set_name="DWG exchange"
        )
    assert first["items"][0]["name"] == "PDF issue" and first["publisher_set_name"] is None
    assert "first publisher set only" in first["note"]
    assert named["items"][0]["name"] == "DWG exchange" and "note" not in named
    assert fake.tapir_requests[-1]["parameters"] == {
        "navigatorMapId": "PublisherSets",
        "publisherSetName": "DWG exchange",
    }


async def test_unknown_publisher_set_surfaces_native_error_and_never_falls_back():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(TapirError, match="GetNavigatorItemTree"):
            await navigator.get_navigator_tree(
                c, "PublisherSets", 19723, publisher_set_name="not present"
            )
    assert fake.tapir_calls == ["GetNavigatorItemTree"]


@pytest.mark.parametrize(
    "args",
    [
        {"navigator_map": "views"},
        {"offset": -1},
        {"limit": 0},
        {"limit": 501},
        {"limit": True},
        {"offset": 1.5},
        {"publisher_set_name": "DWG exchange"},
        {"navigator_map": "PublisherSets", "publisher_set_name": " "},
    ],
)
async def test_invalid_arguments_refused_before_network(args):
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await navigator.get_navigator_tree(c, **args)
    assert not fake.calls


@pytest.mark.parametrize(
    "bad",
    [
        None,
        {},
        {"navigatorItemId": {"guid": "bad"}},
        {
            "navigatorItemId": {"guid": "11111111-1111-1111-1111-111111111111"},
            "name": None,
            "type": "StoryItem",
        },
    ],
)
async def test_malformed_root_is_not_silently_reported_as_empty(bad):
    fake = FakeArchicad(19723)
    fake.navigator_trees["ProjectMap"] = bad
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises((ValueError, TapirError)):
            await navigator.get_navigator_tree(c, port=19723)


@pytest.mark.parametrize("children", [None, {}, [None], [{}], [{"navigatorItem": None}]])
async def test_malformed_children_are_reported(children):
    fake = FakeArchicad(19723)
    fake.navigator_trees["ProjectMap"]["children"] = children
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="navigator"):
            await navigator.get_navigator_tree(c, port=19723)


async def test_leaf_without_children_and_unknown_native_type():
    fake = FakeArchicad(19723)
    root = fake.navigator_trees["ProjectMap"]
    root.pop("children")
    root["type"] = "UnknownItem"
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await navigator.get_navigator_tree(c, port=19723)
    assert result["total"] == 1 and result["items"][0]["type"] == "UnknownItem"


async def test_read_has_no_model_or_receipt_side_effects(tmp_path, monkeypatch):
    fake = FakeArchicad(19723)
    before = deepcopy(fake.navigator_trees)
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path / "receipts"))
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        for map_id in navigator.MAPS:
            await navigator.get_navigator_tree(c, map_id, 19723)
    assert fake.navigator_trees == before and not (tmp_path / "receipts").exists()
    assert set(fake.tapir_calls) == {"GetNavigatorItemTree"}
    assert fake.elements == {}


def test_iterative_flatten_handles_deep_tree_without_recursion():
    root = deepcopy(NAVIGATOR_FIXTURE["trees"]["PublicViewMap"])
    root.pop("children")
    node = root
    for i in range(1, 1200):
        child = {
            "navigatorItemId": {"guid": str(UUID(int=i))},
            "name": str(i),
            "type": "FolderItem",
        }
        node["children"] = [{"navigatorItem": child}]
        node = child
    result = navigator._flatten(root)
    assert len(result) == 1200 and result[-1]["depth"] == 1199
    assert result[-1]["parent_guid"] == result[-2]["guid"]


async def test_large_map_paginates_in_native_order():
    fake = FakeArchicad(19723)
    root = fake.navigator_trees["ProjectMap"]
    root["children"] = [
        {
            "navigatorItem": {
                "navigatorItemId": {"guid": str(UUID(int=i))},
                "name": str(i),
                "type": "FolderItem",
            }
        }
        for i in range(1, 602)
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        page = await navigator.get_navigator_tree(c, port=19723, offset=500, limit=500)
    assert page["total"] == 602 and len(page["items"]) == 102
    assert page["items"][0]["name"] == "500"
