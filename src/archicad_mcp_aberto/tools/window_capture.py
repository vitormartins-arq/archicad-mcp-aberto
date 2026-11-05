"""See the Archicad window as it is, whatever it shows: plan, section, 3D, layout, schedule.

The API has image calls only for the 3D and rendering windows, and saving a picture only
covers some 2D windows. So this asks Windows for the image of the top-level window of the
instance on the given port, found by its project name in the title. Windows only. Reads only:
nothing is sent to Archicad but the project name query, and the window need not be in front,
but it must not be minimized.
"""

from __future__ import annotations

import ctypes
import struct
import sys
import zlib

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port

PW_RENDERFULLCONTENT = 2
SRCCOPY_BI_RGB = 0
DIB_RGB_COLORS = 0
ARCHICAD_TITLE = "Archicad"


def encode_png(width: int, height: int, bgra: bytes) -> bytes:
    """Top-down 32-bit BGRA pixels as an RGB PNG, without an image library."""
    rows = bytearray()
    stride = width * 4
    for y in range(height):
        row = bgra[y * stride : (y + 1) * stride]
        rows.append(0)
        pixels = bytearray(width * 3)
        pixels[0::3] = row[2::4]
        pixels[1::3] = row[1::4]
        pixels[2::3] = row[0::4]
        rows += pixels

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
        + chunk(b"IEND", b"")
    )


def is_blank(bgra: bytes) -> bool:
    return not bgra or bgra[:4] * (len(bgra) // 4) == bgra


def _windows(project_name: str) -> list[tuple[int, str]]:
    user32 = ctypes.windll.user32
    found: list[tuple[int, str]] = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def visit(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value
            if ARCHICAD_TITLE in title and project_name in title:
                found.append((hwnd, title))
        return True

    user32.EnumWindows(callback_type(visit), None)
    return found


def _capture(hwnd: int) -> tuple[int, int, bytes]:
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    for function in (gdi32.CreateCompatibleDC, user32.GetWindowDC):
        function.restype = ctypes.c_void_p
    gdi32.CreateCompatibleBitmap.restype = ctypes.c_void_p
    gdi32.CreateCompatibleBitmap.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleDC.argtypes = [ctypes.c_void_p]
    gdi32.SelectObject.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    gdi32.SelectObject.restype = ctypes.c_void_p
    gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
    gdi32.DeleteDC.argtypes = [ctypes.c_void_p]
    gdi32.GetDIBits.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint,
        ctypes.c_uint,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint,
    ]
    user32.GetWindowDC.argtypes = [ctypes.c_void_p]
    user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    user32.PrintWindow.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    user32.IsIconic.argtypes = [ctypes.c_void_p]
    user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    if user32.IsIconic(hwnd):
        raise ValueError("The Archicad window is minimized: restore it to see it.")
    rect = (ctypes.c_long * 4)()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    width, height = rect[2] - rect[0], rect[3] - rect[1]
    if width <= 0 or height <= 0:
        raise ValueError("The Archicad window has no size.")
    window_dc = user32.GetWindowDC(hwnd)
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    previous = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not user32.PrintWindow(hwnd, memory_dc, PW_RENDERFULLCONTENT):
            raise ValueError("Windows refused to give the image of the Archicad window.")
        # BITMAPINFOHEADER, negative height for top-down rows
        info = struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, SRCCOPY_BI_RGB, 0, 0, 0, 0, 0)
        info_buffer = ctypes.create_string_buffer(info, len(info) + 16)
        pixels = ctypes.create_string_buffer(width * height * 4)
        copied = gdi32.GetDIBits(memory_dc, bitmap, 0, height, pixels, info_buffer, DIB_RGB_COLORS)
        if copied != height:
            raise ValueError("Could not read the image of the Archicad window.")
        return width, height, pixels.raw
    finally:
        gdi32.SelectObject(memory_dc, previous)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)


def crop(width: int, pixels: bytes, region: list[int]) -> tuple[int, int, bytes]:
    """Pixels of region [left, top, right, bottom], clipped to the image."""
    height = len(pixels) // (width * 4)
    left, top = max(region[0], 0), max(region[1], 0)
    right, bottom = min(region[2], width), min(region[3], height)
    if right <= left or bottom <= top:
        raise ValueError("The region is outside the window.")
    rows = bytearray()
    for y in range(top, bottom):
        start = y * width * 4
        rows += pixels[start + left * 4 : start + right * 4]
    return right - left, bottom - top, bytes(rows)


async def open_navigator_item(
    client: ArchicadClient, navigator_item_guid: str, port: int | None = None
) -> dict:
    """Show a story, section, detail, worksheet or layout from the navigator. Changes no element.
    A schedule has no database for this call: open it in Archicad, then look at the window."""
    port = await resolve_port(client, port)
    found = await client.tapir(
        port,
        "GetDatabaseIdFromNavigatorItemId",
        {"navigatorItemIds": [{"navigatorItemId": {"guid": navigator_item_guid}}]},
    )
    row = found["databases"][0]
    if "databaseId" not in row:
        raise ValueError("This navigator item has no window to open from here.")
    await client.tapir(port, "ChangeWindow", {"databaseId": row["databaseId"]})
    return {"port": port, **await client.tapir(port, "GetCurrentWindowType", {})}


async def get_archicad_window_image(
    client: ArchicadClient, port: int | None = None, region: list[int] | None = None
) -> dict:
    """The Archicad window of this port as a PNG, as Windows shows it; region [left, top, right,
    bottom] in pixels of the full window shows only that part."""
    if sys.platform != "win32":
        raise ValueError("Seeing the Archicad window is only available on Windows.")
    port = await resolve_port(client, port)
    info = await client.tapir(port, "GetProjectInfo", {})
    name = info.get("projectName") or ""
    windows = _windows(name)
    if not windows:
        raise ValueError(f"No Archicad window with {name!r} in its title was found.")
    if len(windows) > 1:
        titles = [title for _, title in windows]
        raise ValueError(f"More than one window fits this project: {titles}.")
    hwnd, title = windows[0]
    width, height, pixels = _capture(hwnd)
    if is_blank(pixels):
        raise ValueError("The image came back blank; show the Archicad window and try again.")
    if region:
        width, height, pixels = crop(width, pixels, region)
    return {
        "port": port,
        "title": title,
        "width": width,
        "height": height,
        "png": encode_png(width, height, pixels),
    }
