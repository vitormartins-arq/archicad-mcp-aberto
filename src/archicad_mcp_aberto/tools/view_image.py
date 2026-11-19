"""Look at Archicad: return the active 2D window as an image.

Uses the companion add-on's GetPlanWindowImage (already installed with LAB -
Complemento MCP): it saves the active plan, section, elevation, detail or worksheet
window as a PNG, optionally zoomed to a box in model metres, and restores the zoom.
The project file is never changed or saved. Vitor (19/11/2026): after every edit,
look at the result before reporting it.
"""

from __future__ import annotations

import base64

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port
from archicad_mcp_aberto.tools import scenes

MAX_BYTES = 8 * 1024 * 1024


async def capture_view_image(
    client: ArchicadClient,
    zoom: dict | None = None,
    port: int | None = None,
) -> dict:
    """Return the active 2D window as PNG (base64). zoom: {xMin, yMin, xMax, yMax}."""
    if zoom is not None:
        keys = ("xMin", "yMin", "xMax", "yMax")
        if set(zoom) != set(keys):
            raise ValueError("zoom needs xMin, yMin, xMax and yMax in metres.")
        box = {k: float(zoom[k]) for k in keys}
        if box["xMax"] <= box["xMin"] or box["yMax"] <= box["yMin"]:
            raise ValueError("zoom box must have positive width and height.")
        zoom = box
    port = await resolve_port(client, port)
    response = await scenes._addon(
        client, port, "GetPlanWindowImage", {"zoom": zoom} if zoom else {}
    )
    image = response.get("image")
    if not isinstance(image, str):
        raise ValueError("Archicad returned no window image; show a 2D window first.")
    data = base64.b64decode(image)
    if not data.startswith(b"\x89PNG") or len(data) > MAX_BYTES:
        raise ValueError("The window image is not a PNG or is too large.")
    return {"port": port, "zoom": zoom, "bytes": len(data), "png_base64": image}
