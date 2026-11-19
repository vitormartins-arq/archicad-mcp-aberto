"""Look at Archicad: open a View Map view and return the window as an image.

Uses the ArchicadMcpAberto add-on (CaptureViewImage). It opens the view like a
double-click in the Navigator, saves the active window as a PNG in a temporary
folder and returns it. The project file is never changed or saved. Vitor
(19/11/2026): after every edit, look at the result before reporting it.
"""

from __future__ import annotations

import base64
import tempfile
import uuid
from pathlib import Path

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port
from archicad_mcp_aberto.tools import scenes

MAX_BYTES = 8 * 1024 * 1024


async def capture_view_image(
    client: ArchicadClient,
    view_guid: str | None = None,
    port: int | None = None,
    crop: bool = True,
) -> dict:
    """Open view_guid (a View Map item from get_navigator_tree) if given, else keep the
    active window, and return it as PNG bytes in base64 plus the add-on response."""
    if view_guid is not None:
        view_guid = str(uuid.UUID(view_guid)).upper()
    port = await resolve_port(client, port)
    folder = Path(tempfile.mkdtemp(prefix="archicad-view-"))
    output = folder / f"view-{uuid.uuid4().hex}.png"
    parameters: dict = {"outputPath": str(output), "crop": crop}
    if view_guid:
        parameters["viewGuid"] = view_guid
    response = await scenes._addon(client, port, "CaptureViewImage", parameters)
    if not output.is_file():
        raise ValueError("Archicad did not write the view image.")
    data = output.read_bytes()
    if not data.startswith(b"\x89PNG") or len(data) > MAX_BYTES:
        raise ValueError("The view image is not a PNG or is too large.")
    return {
        "port": port,
        "view_guid": view_guid,
        "path": str(output),
        "bytes": len(data),
        "window_type": response.get("windowType"),
        "png_base64": base64.b64encode(data).decode("ascii"),
    }
