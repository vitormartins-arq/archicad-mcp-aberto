"""capture_view_image: companion add-on stubbed; never live Archicad."""

from pathlib import Path

import pytest

from archicad_mcp_aberto.tools import scenes, view_image

pytestmark = pytest.mark.anyio
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


class Client:
    pass


async def _port(client, port):
    return port or 19723


async def test_opens_view_and_returns_png(monkeypatch):
    calls = []

    async def addon(client, port, name, parameters):
        calls.append((name, parameters))
        Path(parameters["outputPath"]).write_bytes(PNG)
        return {"outputPath": parameters["outputPath"], "windowType": 1}

    monkeypatch.setattr(scenes, "_addon", addon)
    monkeypatch.setattr(view_image, "resolve_port", _port)
    guid = "44a29191-1d57-4b04-9a95-40ebaf9a2e27"
    result = await view_image.capture_view_image(Client(), guid, 19723)
    name, parameters = calls[0]
    assert name == "CaptureViewImage"
    assert parameters["viewGuid"] == guid.upper()
    assert parameters["outputPath"].endswith(".png")
    assert result["bytes"] == len(PNG) and result["window_type"] == 1


async def test_active_window_without_guid(monkeypatch):
    async def addon(client, port, name, parameters):
        assert "viewGuid" not in parameters
        Path(parameters["outputPath"]).write_bytes(PNG)
        return {}

    monkeypatch.setattr(scenes, "_addon", addon)
    monkeypatch.setattr(view_image, "resolve_port", _port)
    assert (await view_image.capture_view_image(Client()))["view_guid"] is None


async def test_refuses_bad_guid_and_missing_or_non_png(monkeypatch):
    monkeypatch.setattr(view_image, "resolve_port", _port)
    with pytest.raises(ValueError):
        await view_image.capture_view_image(Client(), "not-a-guid")

    async def nothing(client, port, name, parameters):
        return {}

    monkeypatch.setattr(scenes, "_addon", nothing)
    with pytest.raises(ValueError, match="did not write"):
        await view_image.capture_view_image(Client())

    async def text(client, port, name, parameters):
        Path(parameters["outputPath"]).write_bytes(b"hello")
        return {}

    monkeypatch.setattr(scenes, "_addon", text)
    with pytest.raises(ValueError, match="PNG"):
        await view_image.capture_view_image(Client())
