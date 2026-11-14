"""Publisher tools against a simulated companion add-on."""

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


async def test_add_layouts_previews_then_verifies(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path / "receipts"))
    layout = "DDDDDDDD-0000-0000-0000-000000000004"
    created = "EEEEEEEE-0000-0000-0000-000000000005"
    state = {"added": False}
    calls = []

    async def fake(client, port, name, parameters=None, timeout=None):
        calls.append((name, parameters))
        if name == "AddPublisherItems":
            state["added"] = True
            return {
                "folderGuid": "F",
                "folderCreated": True,
                "items": [
                    {"layoutGuid": layout, "itemGuid": created, "method": "NewNavigatorView"}
                ],
            }
        return {"sets": [{"name": "PDF", "rootGuid": "G", "output": "local", "path": "C:/old"}]}

    async def tree(self, port, name, parameters=None, timeout=None):
        if parameters["navigatorMapId"] == "LayoutBook":
            return {
                "navigatorItemTree": {
                    "children": [
                        {
                            "navigatorItem": {
                                "type": "LayoutItem",
                                "name": "DC",
                                "uiId": "03.02",
                                "navigatorItemId": {"guid": layout},
                            }
                        }
                    ]
                }
            }
        kids = [
            {
                "navigatorItem": {
                    "type": "LayoutItem",
                    "name": "DC",
                    "navigatorItemId": {"guid": created},
                }
            }
        ]
        return {"navigatorItemTree": {"children": kids if state["added"] else []}}

    monkeypatch.setattr(grids, "_addon", fake)
    monkeypatch.setattr(ArchicadClient, "tapir", tree)
    async with _client() as c:
        preview = await publisher.add_layouts_to_publisher_set(c, "PDF", [layout], folder_name="DC")
        assert not any(n == "AddPublisherItems" for n, _ in calls)
        done = await publisher.add_layouts_to_publisher_set(
            c, "PDF", [layout], None, "DC", 19723, False, preview["confirmation_token"]
        )
    assert done["items"][0]["status"] == "verified"
    assert dict(calls)["AddPublisherItems"] == {
        "parentGuid": "G",
        "layoutGuids": [layout],
        "folderName": "DC",
    }
