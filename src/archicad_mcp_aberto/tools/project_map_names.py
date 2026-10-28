"""Rename Project Map items (views, sections, cameras) through the ArchicadMcpAberto add-on.

Tapir refuses to rename Project Map items, so RenameProjectMapItems lives in our add-on
(addon/). Vitor's rule (28/10/2026): rename views, sections and cameras in the Project
Map, so the name reaches the View Map and the Publisher sets. list_project_map_cameras
lists the cameras with their path, to build the list of new names.

Dry run first; apply the same inputs with the explicit port and the one-use token.
Navigator changes are outside Archicad's Undo, and the project is never saved.
"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID, uuid4
from weakref import WeakKeyDictionary

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port
from archicad_mcp_aberto.tools import scenes
from archicad_mcp_aberto.tools.write import PREVIEW_SECONDS, _digest

MAX_ITEMS = 200

_previews: WeakKeyDictionary[ArchicadClient, dict[str, tuple[float, str]]] = WeakKeyDictionary()


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


def _items(items: list[dict]) -> list[dict]:
    if not 1 <= len(items) <= MAX_ITEMS:
        raise ValueError(f"Pass between 1 and {MAX_ITEMS} items.")
    out, seen = [], set()
    for index, item in enumerate(items):
        name = item.get("name") if isinstance(item, dict) else None
        try:
            guid = str(UUID(str(item.get("guid")))).upper()
        except (AttributeError, ValueError):
            raise ValueError(f"Item {index}: invalid guid.") from None
        if not isinstance(name, str) or not name.strip() or len(name) > 250:
            raise ValueError(f"Item {index}: name needs 1 to 250 characters.")
        if guid in seen:
            raise ValueError(f"Item {index}: the same item appears twice.")
        seen.add(guid)
        out.append({"guid": guid, "name": name})
    return out


async def rename_project_map_items(
    client: ArchicadClient,
    items: list[dict],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/rename up to 200 Project Map items by GUID; each name is read back."""
    wanted = _items(items)
    if not dry_run and port is None:
        raise ValueError("Renaming requires the explicit port of the dry run.")
    port = await resolve_port(client, port)
    digest = _digest({"port": port, "items": wanted})
    previews = _previews.setdefault(client, {})
    now = time.monotonic()
    for token in [t for t, (expiry, _) in previews.items() if expiry <= now]:
        previews.pop(token)
    if dry_run:
        raw = await scenes._addon(
            client, port, "RenameProjectMapItems", {"items": wanted, "dryRun": True}
        )
        rows = _rows(raw, wanted)
        token = str(uuid4())
        previews[token] = (now + PREVIEW_SECONDS, digest)
        return {
            "port": port,
            "dry_run": True,
            "items": [
                {**w, "before": r.get("before"), **({"error": r["error"]} if "error" in r else {})}
                for w, r in zip(wanted, rows, strict=True)
            ],
            "confirmation_token": token,
            "expires_in_seconds": PREVIEW_SECONDS,
            "note": (
                "Nothing renamed yet. Show the list to the user, then repeat the same inputs "
                "with dry_run=false, this port and confirmation_token."
            ),
        }
    entry = previews.pop(confirmation_token or "", None)
    if entry is None or entry[0] <= now:
        raise ValueError("Preview missing, expired or already consumed. Run a new dry run.")
    if entry[1] != digest:
        raise ValueError("Items, names or port changed since the preview. Run a new dry run.")
    raw = await scenes._addon(client, port, "RenameProjectMapItems", {"items": wanted})
    out = []
    for w, r in zip(wanted, _rows(raw, wanted), strict=True):
        row: dict[str, Any] = {**w, "before": r.get("before"), "after": r.get("after")}
        if "error" in r:
            row.update(status="failed", error=r["error"])
        else:
            row["status"] = "verified" if r.get("after") == w["name"] else "verification_failed"
        out.append(row)
    return {
        "port": port,
        "dry_run": False,
        "items": out,
        "renamed": sum(r["status"] == "verified" for r in out),
        "note": "Navigator renames are outside Undo. The project was not saved.",
    }


def _rows(raw: dict, wanted: list[dict]) -> list[dict]:
    rows = raw.get("items")
    if not isinstance(rows, list) or len(rows) != len(wanted):
        raise ValueError("Unexpected RenameProjectMapItems response.")
    if any(not isinstance(r, dict) or str(r.get("guid", "")).upper() != w["guid"]
           for r, w in zip(rows, wanted, strict=True)):  # fmt: skip
        raise ValueError("RenameProjectMapItems answered for other items.")
    return rows
