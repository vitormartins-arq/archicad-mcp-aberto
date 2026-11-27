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


class DpiSetter:
    def __init__(self, v2_supported=True, enter_fails=False, restore_fails=False):
        self.calls = []
        self.v2_supported = v2_supported
        self.enter_fails = enter_fails
        self.restore_fails = restore_fails

    def __call__(self, context):
        value = context.value
        self.calls.append(value)
        if value == 41:
            return None if self.restore_fails else 99
        if self.enter_fails:
            return None
        if value == tool.ctypes.c_void_p(-4).value and not self.v2_supported:
            return None
        return 41


def test_capture_uses_physical_pixel_context_and_restores_it(monkeypatch):
    from types import SimpleNamespace

    setter = DpiSetter()
    monkeypatch.setattr(
        tool.ctypes,
        "windll",
        SimpleNamespace(user32=SimpleNamespace(SetThreadDpiAwarenessContext=setter)),
        raising=False,
    )

    def capture(hwnd):
        assert setter.calls == [tool.ctypes.c_void_p(-4).value]
        return 2586, 1626, b"synthetic-pixels"

    monkeypatch.setattr(tool, "_capture_pixels", capture)
    assert tool._capture(1)[:2] == (2586, 1626)
    assert setter.calls[-1] == 41


def test_original_dpi_restored_even_when_gdi_capture_fails(monkeypatch):
    from types import SimpleNamespace

    setter = DpiSetter()
    monkeypatch.setattr(
        tool.ctypes,
        "windll",
        SimpleNamespace(user32=SimpleNamespace(SetThreadDpiAwarenessContext=setter)),
        raising=False,
    )

    def fail(hwnd):
        raise ValueError("PrintWindow failed")

    monkeypatch.setattr(tool, "_capture_pixels", fail)
    with pytest.raises(ValueError, match="PrintWindow"):
        tool._capture(1)
    assert setter.calls[-1] == 41


def test_older_windows_uses_per_monitor_v1_and_restores_original_context():
    from types import SimpleNamespace

    setter = DpiSetter(v2_supported=False)
    with tool._physical_pixels(SimpleNamespace(SetThreadDpiAwarenessContext=setter)):
        assert setter.calls == [tool.ctypes.c_void_p(-4).value, tool.ctypes.c_void_p(-3).value]
    assert setter.calls[-1] == 41


def test_unsupported_or_failed_dpi_context_refuses_cropped_capture():
    from types import SimpleNamespace

    with pytest.raises(ValueError, match="unavailable"):
        with tool._physical_pixels(SimpleNamespace()):
            pytest.fail("must not capture")
    setter = DpiSetter(enter_fails=True)
    with pytest.raises(ValueError, match="capture refused"):
        with tool._physical_pixels(SimpleNamespace(SetThreadDpiAwarenessContext=setter)):
            pytest.fail("must not capture")


def test_failed_dpi_restoration_is_not_reported_as_a_successful_capture():
    from types import SimpleNamespace

    setter = DpiSetter(restore_fails=True)
    with pytest.raises(RuntimeError, match="restore"):
        with tool._physical_pixels(SimpleNamespace(SetThreadDpiAwarenessContext=setter)):
            pass


class BitmapCopier:
    def __init__(self, success=True):
        self.success = success
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        return int(self.success)


def test_window_copy_reads_existing_surface_without_repaint():
    from types import SimpleNamespace

    copier = BitmapCopier()
    # No PrintWindow member exists on this fake: the safe path cannot invoke it.
    tool._copy_window_bitmap(SimpleNamespace(BitBlt=copier), 11, 22, 2586, 1626)
    assert copier.calls == [(11, 0, 0, 2586, 1626, 22, 0, 0, 0x00CC0020)]
    assert len(copier.argtypes) == 9


def test_failed_bitmap_copy_refuses_instead_of_forcing_repaint():
    from types import SimpleNamespace

    copier = BitmapCopier(success=False)
    with pytest.raises(ValueError, match="displayed pixels"):
        tool._copy_window_bitmap(SimpleNamespace(BitBlt=copier), 11, 22, 2586, 1626)
    assert len(copier.calls) == 1
