"""Return Tapir 1.7.0 preview images as MCP image content."""

import base64
from collections.abc import Awaitable, Callable
from typing import Literal
from uuid import UUID

from mcp.server.fastmcp import Image
from mcp.types import TextContent

from archicad_mcp_aberto.connection import ArchicadClient, TapirError, resolve_port

_MAX_ITEMS = 10
_MAX_BYTES = 5 * 1024 * 1024


def _size(width: int, height: int) -> None:
    if not 16 <= width <= 1024 or not 16 <= height <= 1024 or width * height > 1_048_576:
        raise ValueError("Image dimensions must be 16..1024 pixels and at most 1,048,576 pixels.")


def _content(label: str, rows: list[dict]) -> list:
    content = []
    for row in rows:
        metadata = {"target": row["target"]}
        if "error" in row:
            metadata["error"] = row["error"]
        else:
            metadata.update(mimeType="image/png", bytes=len(row["data"]))
        content.append(TextContent(type="text", text=str(metadata)))
        if "data" in row:
            content.append(Image(data=row["data"], format="png"))
    return content


async def _images(
    targets: list[str], request: Callable[[str], Awaitable[dict]], key: str
) -> list[dict]:
    if not 1 <= len(targets) <= _MAX_ITEMS:
        raise ValueError("Pass between 1 and 10 image targets.")
    rows = []
    for target in targets:
        try:
            result = await request(target)
            encoded = result.get(key)
            if not isinstance(encoded, str):
                raise ValueError("Unexpected image response.")
            data = base64.b64decode(encoded, validate=True)
            if len(data) > _MAX_BYTES:
                raise ValueError("Image exceeds the 5 MiB decoded limit.")
            if not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Tapir response is not PNG data.")
            rows.append({"target": target, "data": data})
        except TapirError as exc:
            rows.append({"target": target, "error": exc.detail or str(exc)})
    return rows


async def get_element_preview(
    client: ArchicadClient,
    element_guids: list[str],
    image_type: Literal["2D", "Section", "3D"] = "3D",
    width: int = 128,
    height: int = 128,
    port: int | None = None,
) -> list:
    _size(width, height)
    guids = [str(UUID(g)).upper() for g in element_guids]
    port = await resolve_port(client, port)

    async def request(guid):
        return await client.tapir(
            port,
            "GetElementPreviewImage",
            {
                "elementId": {"guid": guid},
                "imageType": image_type,
                "format": "png",
                "width": width,
                "height": height,
            },
        )

    return {
        "port": port,
        "content": _content("element", await _images(guids, request, "previewImage")),
    }


async def get_zone_image(
    client: ArchicadClient,
    zone_guids: list[str],
    width: int = 256,
    height: int = 256,
    offset: float = 0.001,
    scale: float = 0.005,
    port: int | None = None,
) -> list:
    _size(width, height)
    if offset < 0 or scale <= 0:
        raise ValueError("offset must be nonnegative and scale positive.")
    guids = [str(UUID(g)).upper() for g in zone_guids]
    port = await resolve_port(client, port)

    async def request(guid):
        return await client.tapir(
            port,
            "GetRoomImage",
            {
                "zoneId": {"guid": guid},
                "format": "png",
                "width": width,
                "height": height,
                "offset": offset,
                "scale": scale,
            },
        )

    return {"port": port, "content": _content("zone", await _images(guids, request, "roomImage"))}


async def get_favorite_preview(
    client: ArchicadClient,
    favorite_names: list[str],
    image_type: Literal["2D", "Section", "3D"] = "3D",
    width: int = 128,
    height: int = 128,
    port: int | None = None,
) -> list:
    _size(width, height)
    if any(not isinstance(n, str) or not n.strip() for n in favorite_names):
        raise ValueError("Favorite names must be non-empty strings.")
    names = [n.strip() for n in favorite_names]
    port = await resolve_port(client, port)

    async def request(name):
        return await client.tapir(
            port,
            "GetFavoritePreviewImage",
            {
                "favorite": name,
                "imageType": image_type,
                "format": "png",
                "width": width,
                "height": height,
            },
        )

    return {
        "port": port,
        "content": _content("favorite", await _images(names, request, "previewImage")),
    }
