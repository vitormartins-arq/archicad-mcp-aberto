"""capture_view_image: companion add-on stubbed; never live Archicad."""

import base64

import pytest

from archicad_mcp_aberto.tools import scenes, view_image

pytestmark = pytest.mark.anyio
PNG = base64.b64encode(bytes([0x89]) + b"PNG" + bytes([13, 10, 26, 10]) + b"0" * 8).decode()


async def _port(client, port):
    return port or 19723


async def test_returns_active_window_and_passes_zoom(monkeypatch):
    calls = []

    async def addon(client, port, name, parameters):
        calls.append((name, parameters))
        return {"image": PNG}

    monkeypatch.setattr(scenes, "_addon", addon)
    monkeypatch.setattr(view_image, "resolve_port", _port)
    result = await view_image.capture_view_image(object())
    assert calls[-1] == ("GetPlanWindowImage", {})
    box = {"xMin": 0, "yMin": 0, "xMax": 2, "yMax": 1}
    result = await view_image.capture_view_image(object(), box, 19723)
    assert calls[-1][1] == {"zoom": {k: float(v) for k, v in box.items()}}
    assert result["png_base64"] == PNG


@pytest.mark.parametrize("zoom", [{"xMin": 0}, {"xMin": 1, "yMin": 0, "xMax": 1, "yMax": 1}])
async def test_bad_zoom_refused_before_network(monkeypatch, zoom):
    async def addon(*args):
        raise AssertionError("no call")

    monkeypatch.setattr(scenes, "_addon", addon)
    with pytest.raises(ValueError):
        await view_image.capture_view_image(object(), zoom)


async def test_no_or_bad_image(monkeypatch):
    monkeypatch.setattr(view_image, "resolve_port", _port)

    async def empty(client, port, name, parameters):
        return {}

    monkeypatch.setattr(scenes, "_addon", empty)
    with pytest.raises(ValueError, match="no window image"):
        await view_image.capture_view_image(object())

    async def text(client, port, name, parameters):
        return {"image": base64.b64encode(b"hello").decode()}

    monkeypatch.setattr(scenes, "_addon", text)
    with pytest.raises(ValueError, match="PNG"):
        await view_image.capture_view_image(object())
