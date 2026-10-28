"""List the Project Map cameras through the ArchicadMcpAberto add-on (read only).

Renaming them is not offered: in a live test (AC30, 28/10/2026) Archicad kept the
camera name after ACAPI_Element_ChangeMemo and refused ACAPI_Navigator_ChangeNavigatorItem
on the Project Map item (0x81060065). Tapir refuses it too. Rename cameras by hand.
"""

from __future__ import annotations

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port
from archicad_mcp_aberto.tools import scenes


async def list_project_map_cameras(client: ArchicadClient, port: int | None = None) -> dict:
    """Every camera of the Project Map: item GUID, name, camera and its path."""
    port = await resolve_port(client, port)
    raw = await scenes._addon(client, port, "GetCameraViews", {"map": "ProjectMap"})
    rows = raw.get("views")
    if not isinstance(rows, list):
        raise ValueError("Unexpected GetCameraViews response.")
    cameras = [
        {
            "guid": row.get("viewGuid"),
            "name": row.get("name"),
            "camera_guid": row.get("cameraGuid"),
            "path": row.get("pathName"),
        }
        for row in rows
        if isinstance(row, dict)
    ]
    return {"port": port, "count": len(cameras), "cameras": cameras}
