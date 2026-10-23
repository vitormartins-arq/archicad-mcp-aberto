import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import drawings
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


async def test_create_drawing_preview_apply_and_verify():
    fake = FakeArchicad(19723)
    data = [
        {
            "view_name": "Ground floor",
            "layout_name": "Planta baixa",
            "name": "AS-01 - SALA",
            "x": 0.15,
            "y": 0.1,
            "drawing_scale": 50,
        }
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        preview = await drawings.create_drawings(client, data, 19723)
        assert preview["items"][0]["parameters"]["angle"] == 0.0
        result = await drawings.create_drawings(
            client, data, 19723, False, preview["confirmation_token"]
        )
    assert result["status"] == "verified"
    request = next(row for row in fake.tapir_requests if row["command"] == "CreateDrawings")
    sent = request["parameters"]["drawingsData"][0]
    assert sent["nameType"] == "CustomName"
    assert sent["drawingScale"] == 50
    assert sent["position"] == {"x": 0.15, "y": 0.1}


async def test_create_drawing_refuses_unknown_targets_and_invalid_inputs():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        with pytest.raises(ValueError, match="view .* missing"):
            await drawings.create_drawings(
                client, [{"view_name": "No view", "layout_name": "Planta baixa", "x": 0, "y": 0}]
            )
        with pytest.raises(ValueError, match="layout .* missing"):
            await drawings.create_drawings(
                client, [{"view_name": "Ground floor", "layout_name": "No layout", "x": 0, "y": 0}]
            )
        with pytest.raises(ValidationError):
            await drawings.create_drawings(
                client,
                [
                    {
                        "view_name": "Ground floor",
                        "layout_name": "Planta baixa",
                        "x": 0,
                        "y": 0,
                        "angle": "0",
                    }
                ],
            )
    assert "CreateDrawings" not in fake.tapir_calls


async def test_create_drawing_requires_explicit_port_and_single_use_token():
    fake = FakeArchicad(19723)
    data = [{"view_name": "Ground floor", "layout_name": "Planta baixa", "x": 0, "y": 0}]
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        preview = await drawings.create_drawings(client, data, 19723)
        with pytest.raises(ValueError, match="explicit port"):
            await drawings.create_drawings(client, data, None, False, preview["confirmation_token"])
        await drawings.create_drawings(client, data, 19723, False, preview["confirmation_token"])
        with pytest.raises(ValueError, match="already consumed"):
            await drawings.create_drawings(
                client, data, 19723, False, preview["confirmation_token"]
            )
