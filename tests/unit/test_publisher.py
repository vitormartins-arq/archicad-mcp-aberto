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
