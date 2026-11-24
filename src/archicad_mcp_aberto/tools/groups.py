"""Explicit, reversible Suspend Groups mode; never changes group membership."""

from archicad_mcp_aberto.connection import ArchicadError, resolve_port
from archicad_mcp_aberto.tools import grids, write


async def get_suspend_groups(client, port=None):
    """Read the selected instance's native editing mode and strict project identity."""
    port = await resolve_port(client, port)
    state = await grids._addon(client, port, "GetSuspendGroups", {})
    if type(state.get("suspended")) is not bool or not isinstance(state.get("context"), dict):
        raise ValueError("Incomplete native Suspend Groups state.")
    context = state["context"]
    if not all(
        k in context
        for k in (
            "sessionId",
            "projectEpoch",
            "projectPath",
            "modificationStamp",
            "untitled",
            "teamwork",
        )
    ):
        raise ValueError("Missing native project identity; refusing mode change.")
    return {"port": port, **state}


async def _plan(client, values, port, operation):
    state = await get_suspend_groups(client, port)
    native = {k: v for k, v in state.items() if k != "port"}
    return {
        "operation": operation,
        "target": {"port": state["port"], "project": state["context"]},
        "native_state": native,
        "restore_suspended": state["suspended"],
        "items": [
            {
                "index": 0,
                "status": "ready",
                "before": state["suspended"],
                "parameters": {"suspended": values[0]},
            }
        ],
    }


async def _dispatch(client, receipt):
    item = receipt["items"][0]
    port = receipt["target"]["port"]
    try:
        result = await grids._addon(
            client,
            port,
            "SetSuspendGroups",
            {**item["parameters"], "expectedState": receipt["native_state"]},
            timeout=receipt["write_timeout_seconds"],
        )
        item["native_result"] = result
        after = await get_suspend_groups(client, port)
        item["after"] = after["suspended"]
        identity = ("sessionId", "projectEpoch", "projectPath", "untitled", "teamwork")
        same_project = all(after["context"][k] == receipt["target"]["project"][k] for k in identity)
        verified = (
            result.get("verified") is True
            and result.get("previousSuspended") is item["before"]
            and result.get("suspended") is item["parameters"]["suspended"]
            and after["suspended"] is item["parameters"]["suspended"]
            and same_project
        )
        item["status"] = "verified" if verified else "verification_failed"
    except (ArchicadError, ValueError) as exc:
        item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Read the current mode before any new action; never retry this token."


async def set_suspend_groups(client, suspended, port=None, dry_run=True, confirmation_token=None):
    """Preview/apply a mode value, never a toggle. Restore with a NEW preview of restore_suspended.

    Suspend before previewing grouped-element GDL edits; restore the previous mode even
    when an edit fails. Does not save, ungroup, select, or expand the requested element IDs.
    """
    if type(suspended) is not bool:
        raise ValueError("suspended must be a boolean.")
    return await write._write(
        client,
        [suspended],
        port,
        dry_run,
        confirmation_token,
        "set_suspend_groups",
        planner_override=_plan,
        dispatcher_override=_dispatch,
        completion_note="No elements or memberships changed; no project saved. Restore the prior "
        "mode with a new set_suspend_groups preview, not Undo.",
    )
