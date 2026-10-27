"""create_layout_subsets and create_layouts in a subset, against the simulated Archicad."""

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import documents, layout_book
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
ROOT = "88888888-8888-4888-8888-000000000010"  # Layout Book root "Projeto teste"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


async def apply(tool, c, items):
    preview = await tool(c, items, 19723)
    return preview, await tool(c, items, 19723, False, preview["confirmation_token"])


def subset_guid(fake, name):
    nodes = fake._nav_items_of(fake.navigator_trees["LayoutBook"])
    return next(n["navigatorItemId"]["guid"] for n in nodes if n["name"] == name)


async def test_subsets_nested_and_layout_put_inside():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(
            layout_book.create_layout_subsets,
            c,
            [{"name": "Executivo", "prefix": "EX", "numbering": "01"}],
        )
        assert preview["items"][0]["parent_guid"] == ROOT
        assert result["status"] == "verified"
        _, nested = await apply(
            layout_book.create_layout_subsets, c, [{"name": "Plantas", "parent": "executivo"}]
        )
        assert nested["status"] == "verified"
        _, layout = await apply(
            documents.create_layouts,
            c,
            [{"name": "Planta térreo", "master": "A3 Paisagem", "subset": "Plantas"}],
        )
    requests = [r for r in fake.tapir_requests if r["command"] == "CreateLayoutSubset"]
    assert requests[0]["parameters"] == {
        "subsetsData": [{"name": "Executivo", "ownPrefix": "EX", "numberingStyle": "01"}]
    }
    assert requests[1]["parameters"]["subsetsData"][0]["parentNavigatorItemId"] == {
        "guid": subset_guid(fake, "Executivo")
    }
    assert layout["status"] == "verified"
    assert layout["items"][0]["subset_name"] == "Plantas"
    plantas = next(
        n for n in fake._nav_items_of(fake.navigator_trees["LayoutBook"]) if n["name"] == "Plantas"
    )
    assert [c["navigatorItem"]["name"] for c in plantas["children"]] == ["Planta térreo"]


async def test_same_name_under_the_same_parent_is_refused():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        await apply(layout_book.create_layout_subsets, c, [{"name": "Executivo"}])
        with pytest.raises(ValueError, match="already has a subset"):
            await layout_book.create_layout_subsets(c, [{"name": "EXECUTIVO"}], 19723)
        with pytest.raises(ValueError, match="twice"):
            await layout_book.create_layout_subsets(c, [{"name": "A"}, {"name": "a"}], 19723)
        with pytest.raises(ValueError, match="subset 'Nada' does not exist"):
            await layout_book.create_layout_subsets(c, [{"name": "A", "parent": "Nada"}], 19723)
        with pytest.raises(ValueError, match="subset 'Nada' does not exist"):
            await documents.create_layouts(
                c, [{"name": "X", "master": "A3 Paisagem", "subset": "Nada"}], 19723
            )


def test_bad_subset_input_is_refused():
    with pytest.raises(ValidationError):
        layout_book.SubsetCreate.model_validate({"name": " Executivo"})
    with pytest.raises(ValidationError):
        layout_book.SubsetCreate.model_validate({"name": "Executivo", "numbering": "I"})
