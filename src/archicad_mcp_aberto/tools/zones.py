"""Update Zones (Design > Update Zones), through Tapir 1.7.0.

UpdateZones recalculates every zone of the project at once: geometry from its boundary,
zone stamps and connected elements. There is no per-zone choice. The command answers one
execution result and Tapir cannot read zone geometry back, so the result stays
"unverified"; the MCP counts zones before and after. Never saves.
"""

from __future__ import annotations

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError, TapirError
from archicad_mcp_aberto.tools import write


class ZoneUpdate(write.InputModel):
    keep_stamp_position: bool = True
    undo_top_trim: bool = False
    undo_bottom_trim: bool = False


async def _zone_count(client, port, timeout=None) -> int:
    extra = {} if timeout is None else {"timeout": timeout}
    result = await client.command(port, "GetElementsByType", {"elementType": "Zone"}, **extra)
    rows = result.get("elements")
    if not isinstance(rows, list):
        raise ValueError("Unexpected zone list response.")
    return len(rows)


async def _plan(client, updates, port, operation):
    port, target, _ = await write._context(client, port)
    count = await _zone_count(client, port)
    if not count:
        raise ValueError("The project has no zones to update.")
    update = updates[0]
    item = {
        "index": 0,
        "status": "ready",
        "zone_count": count,
        "parameters": {
            "keepStampPosition": update.keep_stamp_position,
            "undoTopTrim": update.undo_top_trim,
            "undoBottomTrim": update.undo_bottom_trim,
        },
    }
    return {"operation": operation, "target": target, "items": [item]}


async def _dispatch(client, receipt):
    item, port = receipt["items"][0], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    try:
        item["write_response"] = await client.tapir(
            port, "UpdateZones", item["parameters"], timeout=timeout
        )
    except TapirError as exc:
        if exc.detail:
            item.update(status="failed", error=exc.detail)
            return
        item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Outcome is unknown. Inspect Archicad; do not retry this plan."
        return
    except ArchicadError as exc:
        item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Outcome is unknown. Inspect Archicad; do not retry this plan."
        return
    item["status"] = "unverified"
    try:
        item["zone_count_after"] = await _zone_count(client, port, timeout)
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    if item["zone_count_after"] != item["zone_count"]:
        item.update(status="verification_failed", mismatches=["zone_count"])
    else:
        item["note"] = "Archicad reported success; check zone areas and stamps in Archicad."


async def update_zones(
    client: ArchicadClient,
    port: int | None = None,
    keep_stamp_position: bool = True,
    undo_top_trim: bool = False,
    undo_bottom_trim: bool = False,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply recalculating every zone of the project (Update Zones)."""
    update = ZoneUpdate(
        keep_stamp_position=keep_stamp_position,
        undo_top_trim=undo_top_trim,
        undo_bottom_trim=undo_bottom_trim,
    )
    return await write._write(
        client,
        [update],
        port,
        dry_run,
        confirmation_token,
        "update_zones",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
