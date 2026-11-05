"""Seeing the Archicad window: the parts that do not need a real window."""

import struct
import zlib

import pytest

from archicad_mcp_aberto.tools import window_capture as tool


def pixels(width, height, bgra=(10, 20, 30, 255)):
    return bytes(bgra) * (width * height)


def test_png_holds_the_pixels_as_rgb():
    png = tool.encode_png(2, 1, pixels(2, 1))
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert struct.unpack(">II", png[16:24]) == (2, 1)
    start = png.index(b"IDAT") + 4
    length = struct.unpack(">I", png[start - 8 : start - 4])[0]
    assert zlib.decompress(png[start : start + length]) == bytes([0, 30, 20, 10, 30, 20, 10])


def test_a_single_colour_is_blank():
    assert tool.is_blank(pixels(3, 3))
    assert not tool.is_blank(pixels(1, 1) + pixels(1, 1, (1, 2, 3, 255)))


def test_crop_clips_to_the_window():
    image = pixels(1, 1, (1, 1, 1, 255)) + pixels(1, 1, (2, 2, 2, 255))
    assert tool.crop(2, image, [1, 0, 9, 9]) == (1, 1, pixels(1, 1, (2, 2, 2, 255)))
    with pytest.raises(ValueError, match="outside"):
        tool.crop(2, image, [5, 5, 9, 9])


class Client:
    probe_timeout = 1.0

    def __init__(self):
        self.zoom = {"xMin": 0.0, "yMin": 0.0, "xMax": 10.0, "yMax": 5.0}

    async def command(self, port, name, parameters=None, timeout=None):
        return {}

    async def own_addon(self, port, name, parameters=None, timeout=None):
        assert name == "WindowZoom"
        if parameters.get("zoom"):
            self.zoom = parameters["zoom"]
        return {"zoom": dict(self.zoom)}


@pytest.mark.anyio
async def test_pan_keeps_the_zoom_and_moves_the_view():
    result = await tool.pan_window(Client(), 2.0, -1.0, 19723)
    assert result["zoom"] == {"xMin": 2.0, "xMax": 12.0, "yMin": -1.0, "yMax": 4.0}
