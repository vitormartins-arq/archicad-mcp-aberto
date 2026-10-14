"""Lock and unlock elements (Edit > Locking), through Tapir 1.7.0.

This is Archicad's manual lock, not Teamwork reservation. LockElements and
UnlockElements answer one execution result for the whole batch, so the MCP reads every
element's editability back (FilterElements IsEditable) to tell what really changed.
Unlock refuses elements on a locked layer: unlocking them would not make them editable.
Both use the shared preview, single-use token and receipts. Never saves.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError, TapirError
from archicad_mcp_aberto.tools import drafting, edit, layers, read, write

MAX_ELEMENTS = 100
COMMANDS = {"lock_elements": "LockElements", "unlock_elements": "UnlockElements"}


async def _editable_set(client, port, guids, timeout=None) -> set[str]:
    extra = {} if timeout is None else {"timeout": timeout}
    response = await client.tapir(
        port,
        "FilterElements",
        {"elements": read.element_ids(guids), "filters": ["IsEditable"]},
        **extra,
    )
    rows = response.get("elements")
    if not isinstance(rows, list):
        raise ValueError("Unexpected editability response.")
    return {str(UUID(r["elementId"]["guid"])).upper() for r in rows}


async def _locked_layers(client, port, indices: set) -> set:
    by_index = {
        r.get("index"): str(UUID(r["attributeId"]["guid"])).upper()
        for r in await drafting._attributes(client, port, "Layer")
        if isinstance(r.get("attributeId"), dict)
    }
    wanted = [by_index[i] for i in indices if i in by_index]
    rows = await layers._details(client, port, wanted) if wanted else []
    return {r.get("index") for r in rows if isinstance(r, dict) and r.get("isLocked") is True}


async def _plan(client, guids, port, operation):
    if operation == "lock_elements":
        port, target, rows = await edit._editable(client, guids, port)
    else:
        port, target, _ = await write._context(client, port)
        result = await client.tapir(
            port,
            "GetDetailsOfElements",
            {"elements": read.element_ids(guids), "fields": write.DETAIL_FIELDS},
        )
        rows = result.get("detailsOfElements")
        if not isinstance(rows, list) or len(rows) != len(guids):
            raise ValueError("Unexpected element details response.")
        for guid, row in zip(guids, rows, strict=True):
            if not isinstance(row, dict) or "error" in row or row.get("type") in (None, "Unknown"):
                raise ValueError(f"Element {guid} does not exist or cannot be read.")
            if row.get("hotlinkId"):
                raise ValueError(f"Element {guid} belongs to a hotlink.")
        editable = await _editable_set(client, port, guids)
        already = [g for g in guids if g in editable]
        if already:
            raise ValueError(f"Not locked (already editable): {already}.")
        locked = await _locked_layers(client, port, {r.get("layerIndex") for r in rows})
        on_locked = [g for g, r in zip(guids, rows, strict=True) if r.get("layerIndex") in locked]
        if on_locked:
            raise ValueError(f"On a locked layer (unlock the layer instead): {on_locked}.")
    items = [
        {
            "index": index,
            "status": "ready",
            "element_guid": guid,
            "elementType": row.get("type"),
            "floorIndex": row.get("floorIndex"),
            "layerIndex": row.get("layerIndex"),
            "editable_before": operation == "lock_elements",
            "parameters": {"elementId": {"guid": guid}},
        }
        for index, (guid, row) in enumerate(zip(guids, rows, strict=True))
    ]
    return {"operation": operation, "target": target, "items": items}


async def _dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    command = COMMANDS[receipt["operation"]]
    failure: Any = None
    try:
        receipt["raw_response"] = await client.tapir(
            port, command, {"elements": [i["parameters"] for i in items]}, timeout=timeout
        )
    except TapirError as exc:
        if not exc.detail:
            for item in items:
                item.update(status="unknown", error=str(exc))
            receipt["warning"] = "Outcome is unknown. Inspect Archicad; do not retry this plan."
            return
        failure = exc.detail  # Archicad said the batch failed; still read what changed.
    except ArchicadError as exc:
        for item in items:
            item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Outcome is unknown. Inspect Archicad; do not retry this plan."
        return
    try:
        editable = await _editable_set(client, port, [i["element_guid"] for i in items], timeout)
    except (ArchicadError, ValueError, KeyError) as exc:
        for item in items:
            item.update(status="failed" if failure else "unverified")
            if failure:
                item["error"] = failure
        receipt["verification_error"] = str(exc)
        return
    wanted = receipt["operation"] == "unlock_elements"
    for item in items:
        item["editable_after"] = item["element_guid"] in editable
        changed = item["editable_after"] == wanted
        if failure:
            # Reported failed, yet this element changed: the batch outcome is mixed.
            item.update(status="unknown" if changed else "failed", error=failure)
        else:
            item["status"] = "verified" if changed else "verification_failed"
            if not changed:
                item["mismatches"] = ["editable"]


async def _run(client, element_guids, port, dry_run, token, operation) -> dict:
    guids = [str(UUID(g)).upper() for g in element_guids]
    edit._unique(guids, MAX_ELEMENTS)
    return await write._write(
        client,
        guids,
        port,
        dry_run,
        token,
        operation,
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )


async def lock_elements(
    client: ArchicadClient,
    element_guids: list[str],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply locking up to 100 editable, non-hotlinked elements."""
    return await _run(client, element_guids, port, dry_run, confirmation_token, "lock_elements")


async def unlock_elements(
    client: ArchicadClient,
    element_guids: list[str],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply unlocking up to 100 locked elements that are not on a locked layer."""
    return await _run(client, element_guids, port, dry_run, confirmation_token, "unlock_elements")
