"""GetHotlinks coverage uses a source-derived fake and never opens Archicad."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import hotlinks
from tests.unit.fake_archicad import HOTLINKS_FIXTURE, FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
ROOT = "10000000-0000-4000-8000-000000000001"
CHILD = "10000000-0000-4000-8000-000000000002"
XREF = "20000000-0000-4000-8000-000000000001"


def client(fake):
    return ArchicadClient(transport=fake_transport(fake))


async def test_tree_is_flattened_in_preorder_with_parent_and_depth():
    fake = FakeArchicad(19723, hotlinks_fixture=True)
    async with client(fake) as c:
        result = await hotlinks.list_hotlinks(c, 19723)
    assert result["total"] == 3
    assert [row["guid"] for row in result["hotlinks"]] == [ROOT, CHILD, XREF]
    assert result["hotlinks"][0]["parent_guid"] is None
    assert result["hotlinks"][1]["parent_guid"] == ROOT
    assert [row["depth"] for row in result["hotlinks"]] == [0, 1, 0]
    assert result["hotlinks"][2]["type"] == "XRef"
    assert fake.tapir_requests == [{"command": "GetHotlinks", "parameters": {}}]


@pytest.mark.parametrize(
    ("query", "guid"),
    [("kitchen", CHILD), ("xref", XREF), ("survey.dwg", XREF)],
)
async def test_filter_matches_name_type_or_location(query, guid):
    async with client(FakeArchicad(19723, hotlinks_fixture=True)) as c:
        result = await hotlinks.list_hotlinks(c, 19723, query=query)
    assert result["total"] == 1 and result["hotlinks"][0]["guid"] == guid


async def test_pagination_applies_after_filtering():
    async with client(FakeArchicad(19723, hotlinks_fixture=True)) as c:
        result = await hotlinks.list_hotlinks(c, 19723, offset=1, limit=1)
    assert result["total"] == 3
    assert [row["guid"] for row in result["hotlinks"]] == [CHILD]


@pytest.mark.parametrize(
    "change, message",
    [
        (lambda tree: tree[0].update(hotlinkNodeId={"guid": "bad"}), "GUID"),
        (lambda tree: tree[0].update(type="IFC"), "details"),
        (lambda tree: tree[0].update(children={}), "children"),
        (
            lambda tree: tree[0]["children"][0].update(
                hotlinkNodeId=deepcopy(tree[0]["hotlinkNodeId"])
            ),
            "Duplicate",
        ),
    ],
)
async def test_malformed_or_duplicate_nodes_are_rejected(monkeypatch, change, message):
    response = deepcopy(HOTLINKS_FIXTURE["response"])
    change(response["hotlinks"])
    monkeypatch.setitem(HOTLINKS_FIXTURE, "response", response)
    async with client(FakeArchicad(19723, hotlinks_fixture=True)) as c:
        with pytest.raises(ValueError, match=message):
            await hotlinks.list_hotlinks(c, 19723)


@pytest.mark.parametrize("kwargs", [{"offset": -1}, {"limit": 0}, {"limit": 501}, {"query": 2}])
async def test_invalid_page_or_query_is_rejected_before_command(kwargs):
    fake = FakeArchicad(19723, hotlinks_fixture=True)
    async with client(fake) as c:
        with pytest.raises(ValueError):
            await hotlinks.list_hotlinks(c, port=19723, **kwargs)
    assert fake.tapir_calls == []


def test_fixture_is_explicitly_source_derived_not_live():
    fixture = json.loads(
        (Path(__file__).parents[1] / "fixtures" / "tapir170_hotlinks_documented.json").read_text()
    )
    assert fixture["provenance"]["live_capture"] is False
    assert fixture["provenance"]["tapir_version"] == "1.7.0"
    assert fixture["provenance"]["commit"] == "02691b5d680b60c73317e8e49b78ab14dfd4c9d8"
