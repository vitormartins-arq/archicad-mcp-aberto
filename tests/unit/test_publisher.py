"""Publisher tools against a simulated companion add-on."""

from pathlib import Path

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import grids, publisher
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio


@pytest.fixture
def addon(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path / "receipts"))
    calls = []
    out = tmp_path / "out"
    out.mkdir()

    async def fake(client, port, name, parameters=None, timeout=None):
        calls.append(name)
        if name == "PublishPublisherSet":
            (out / "a.pdf").write_bytes(b"x")
            return {"published": True}
        return {"sets": [{"name": "PDF", "rootGuid": "G", "output": "local", "path": "C:/old"}]}

    monkeypatch.setattr(grids, "_addon", fake)
    return calls, out


def _client():
    return ArchicadClient(transport=fake_transport(FakeArchicad(19723)))


async def test_preview_does_not_publish_and_apply_reports_files(addon):
    calls, out = addon
    async with _client() as c:
        preview = await publisher.publish_publisher_set(c, "PDF", str(out), 19723)
        assert "PublishPublisherSet" not in calls
        done = await publisher.publish_publisher_set(
            c, "PDF", str(out), 19723, False, preview["confirmation_token"]
        )
    item = done["items"][0]
    assert item["status"] == "verified"
    assert item["files_written"] == ["a.pdf"]
    assert item["saved_path_after"] == "C:/old"


async def test_missing_folder_or_set_is_refused(addon):
    _, out = addon
    async with _client() as c:
        with pytest.raises(ValueError):
            await publisher.publish_publisher_set(c, "PDF", str(out / "nope"), 19723)
        with pytest.raises(ValueError):
            await publisher.publish_publisher_set(c, "X", str(out), 19723)


def _pdf(path, pages):
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(100, 100)
    with open(path, "wb") as handle:
        writer.write(handle)


SEL_A = "AAAAAAAA-0000-0000-0000-000000000001"
SEL_B = "BBBBBBBB-0000-0000-0000-000000000002"
TREE = {
    "navigatorItemTree": {
        "children": [
            {
                "navigatorItem": {
                    "type": "LayoutItem",
                    "name": "TERREO",
                    "uiId": "03.02",
                    "navigatorItemId": {"guid": SEL_A},
                }
            },
            {
                "navigatorItem": {
                    "type": "LayoutItem",
                    "name": "1 ANDAR",
                    "uiId": "03.03",
                    "navigatorItemId": {"guid": SEL_B},
                }
            },
        ]
    }
}


async def test_selection_is_merged_into_one_pdf_in_order(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path / "receipts"))
    out = tmp_path / "out"
    out.mkdir()
    sent = {}

    async def fake(client, port, name, parameters=None, timeout=None):
        if name == "PublishPublisherSet":
            sent.update(parameters)
            folder = tmp_path.joinpath(parameters["outputPath"])
            _pdf(folder / "03.03 1 ANDAR.pdf", 1)
            _pdf(folder / "03.02 TERREO.pdf", 2)
            return {"published": True}
        return {"sets": [{"name": "PDF", "rootGuid": "G", "output": "local", "path": "C:/old"}]}

    async def tree(self, port, name, parameters=None, timeout=None):
        return TREE["navigatorItemTree"] and TREE

    monkeypatch.setattr(grids, "_addon", fake)
    monkeypatch.setattr(ArchicadClient, "tapir", tree)
    async with _client() as c:
        preview = await publisher.publish_publisher_set(
            c,
            "PDF",
            str(out),
            19723,
            selected_item_guids=[SEL_A, SEL_B],
            merged_pdf_name="Bloco 01",
        )
        done = await publisher.publish_publisher_set(
            c,
            "PDF",
            str(out),
            19723,
            False,
            preview["confirmation_token"],
            [SEL_A, SEL_B],
            "Bloco 01",
        )
    item = done["items"][0]
    assert sent["selectedItemGuids"] == [SEL_A, SEL_B]
    assert sent["outputPath"] != str(out)
    assert item["status"] == "verified"
    assert item["merged_from"] == ["03.02 TERREO.pdf", "03.03 1 ANDAR.pdf"]
    assert item["merged_pages"] == 3
    assert sorted(p.name for p in out.iterdir()) == ["Bloco 01.pdf"]


async def test_unknown_selection_and_merge_without_selection_are_refused(addon, monkeypatch):
    _, out = addon

    async def tree(self, port, name, parameters=None, timeout=None):
        return TREE

    monkeypatch.setattr(ArchicadClient, "tapir", tree)
    async with _client() as c:
        with pytest.raises(ValueError):
            await publisher.publish_publisher_set(
                c,
                "PDF",
                str(out),
                19723,
                selected_item_guids=["CCCCCCCC-0000-0000-0000-000000000003"],
            )
        with pytest.raises(ValueError):
            await publisher.publish_publisher_set(c, "PDF", str(out), 19723, merged_pdf_name="x")


async def test_save_layouts_merges_in_order_and_writes_only_the_merged_pdf(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path / "receipts"))
    out = tmp_path / "out"
    out.mkdir()
    ground = "DDDDDDDD-0000-0000-0000-000000000004"
    first = "EEEEEEEE-0000-0000-0000-000000000005"
    calls = []

    async def fake(client, port, name, parameters=None, timeout=None):
        calls.append(name)
        folder = Path(parameters["outputPath"])
        _pdf(folder / "03.02 TERREO.pdf", 1)
        _pdf(folder / "03.03 1 ANDAR.pdf", 2)
        return {"files": [{"file": "03.02 TERREO.pdf"}, {"file": "03.03 1 ANDAR.pdf"}]}

    async def tree(self, port, name, parameters=None, timeout=None):
        rows = [(ground, "03.02", "TERREO"), (first, "03.03", "1 ANDAR")]
        kids = [
            {
                "navigatorItem": {
                    "type": "LayoutItem",
                    "uiId": i,
                    "name": n,
                    "navigatorItemId": {"guid": g},
                }
            }
            for g, i, n in rows
        ]
        return {"navigatorItemTree": {"children": kids}}

    monkeypatch.setattr(grids, "_addon", fake)
    monkeypatch.setattr(ArchicadClient, "tapir", tree)
    async with _client() as c:
        preview = await publisher.save_layouts_as_pdf(c, [ground, first], str(out), "Bloco 01")
        assert not calls
        done = await publisher.save_layouts_as_pdf(
            c, [ground, first], str(out), "Bloco 01", 19723, False, preview["confirmation_token"]
        )
    item = done["items"][0]
    assert item["status"] == "verified"
    assert item["merged_pages"] == 3
    assert sorted(p.name for p in out.iterdir()) == ["Bloco 01.pdf"]
