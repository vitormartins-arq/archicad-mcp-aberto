"""Scoped top-surface RGB snapshots; native floor geometry and cover fills stay intact."""

from uuid import UUID

from archicad_mcp_aberto.connection import ArchicadError, resolve_port
from archicad_mcp_aberto.tools import grids, model_tasks, views, write


async def get_floor_surface_backgrounds(client, guids, port=None):
    ids = _ids(guids)
    port = await resolve_port(client, port)
    result = await grids._addon(client, port, "GetFloorSurfaceBackgroundState", {"guids": ids})
    rows = result.get("slabs")
    if not isinstance(rows, list) or len(rows) != len(ids):
        raise ValueError("Incomplete floor surface audit.")
    return {"port": port, **result}


def _ids(guids):
    if not 1 <= len(guids) <= 200:
        raise ValueError("Pass 1..200 explicit Slab GUIDs.")
    ids = [str(UUID(g)).upper() for g in guids]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate Slab GUID.")
    return ids


async def _plan(client, requests, port, operation):
    (request,) = requests
    port = await resolve_port(client, port)
    native = await grids._addon(
        client,
        port,
        "PlanFloorSurfaceBackgrounds",
        {"guids": request["guids"], "scope": request["scope_id"]},
    )
    rows, context = native.get("slabs"), native.get("context")
    if (
        not isinstance(rows, list)
        or len(rows) != len(request["guids"])
        or not isinstance(context, dict)
    ):
        raise ValueError("Incomplete native floor plan.")
    if context.get("isUntitled") is not True:
        task = model_tasks._task(client, request["task_token"], port)
        if model_tasks._identity(context) != model_tasks._identity(task["project"]):
            raise ValueError("Backup belongs to another project/session.")
    before_view = None
    if request["view_guid"]:
        (before_view,) = await views._settings(client, port, [request["view_guid"]])
        if before_view.get("graphicOverrideCombination") != native.get("baseCombinationName"):
            raise ValueError(
                "Open the target saved view with its stored override combination first."
            )
    for guid, row in zip(request["guids"], rows, strict=True):
        if row.get("guid", "").strip("{}").upper() != guid or "error" in row:
            raise ValueError("Native preview returned another floor or an error.")
        for field in ("preserved", "preservedVisual", "surfaceColor"):
            if not isinstance(row.get(field), dict):
                raise ValueError("Missing native preservation snapshot.")
    return {
        "operation": operation,
        "target": {"port": port, "project": context},
        "native_plan": native,
        "view_before": before_view,
        "items": [{"index": 0, "status": "ready", "parameters": request}],
        "color_link": "RGB snapshot; explicitly resync after changing a surface or its assignment.",
        "metadata": (
            "Creates a fresh scoped property group, RGB-only rules and a cloned combination; "
            "does not edit existing pens or rules."
        ),
        "revert_note": (
            "Restore the previous saved-view combination separately; native Undo must be "
            "validated for the scoped model/override transaction."
        ),
    }


async def _dispatch(client, receipt):
    item = receipt["items"][0]
    request, port = item["parameters"], receipt["target"]["port"]
    try:
        result = await grids._addon(
            client,
            port,
            "SetFloorSurfaceBackgrounds",
            {
                "guids": request["guids"],
                "scope": request["scope_id"],
                "expectedPlan": receipt["native_plan"],
            },
            timeout=receipt["write_timeout_seconds"],
        )
        item["native_result"] = result
        if result.get("verified") is not True or result.get("slabCount") != len(request["guids"]):
            raise ValueError("Native application was not verified; inspect before retrying.")
        after = await get_floor_surface_backgrounds(client, request["guids"], port)
        for before, actual in zip(receipt["native_plan"]["slabs"], after["slabs"], strict=True):
            for field in ("guid", "surfaceGuid", "preserved", "preservedVisual", "surfaceColor"):
                if write._mismatches(before[field], actual.get(field)):
                    raise ValueError(f"Floor preservation read-back failed: {field}.")
            if write._mismatches(before["surfaceColor"], actual.get("effectiveBackgroundRGB")):
                raise ValueError("Effective background differs from top-surface RGB.")
        item["floor_readback"] = after["slabs"]
        if request["view_guid"]:
            (current,) = await views._settings(client, port, [request["view_guid"]])
            if current != receipt["view_before"]:
                raise ValueError("Saved view changed during application; it was not overwritten.")
            # Only this field is sent: never store current zoom or user layer changes.
            item["saved_view_write_attempted"] = True
            response = await client.tapir(
                port,
                "SetViewSettings",
                {
                    "navigatorItemIdsWithViewSettings": [
                        {
                            "navigatorItemId": {"guid": request["view_guid"]},
                            "viewSettings": {
                                "graphicOverrideCombination": result["combinationName"]
                            },
                        }
                    ]
                },
                timeout=receipt["write_timeout_seconds"],
            )
            item["saved_view_response"] = response
            (actual,) = await views._settings(client, port, [request["view_guid"]])
            expected = {
                **receipt["view_before"],
                "graphicOverrideCombination": result["combinationName"],
            }
            if views._mismatches(expected, actual):
                raise ValueError(
                    "Saved-view preservation verification failed; inspect receipt, do not retry."
                )
            item["view_readback"] = actual
        item["status"] = "verified"
    except (ArchicadError, ValueError, KeyError, TypeError) as exc:
        item.update(status="unknown", error=str(exc))
        if isinstance(exc, ArchicadError):
            item["native_error"] = exc.detail


async def set_floor_surface_backgrounds(
    client,
    guids,
    scope_id,
    port=None,
    view_guid=None,
    task_token=None,
    dry_run=True,
    confirmation_token=None,
):
    request = {
        "guids": _ids(guids),
        "scope_id": str(UUID(scope_id)).upper(),
        "view_guid": str(UUID(view_guid)).upper() if view_guid else None,
        "task_token": task_token,
    }
    return await write._write(
        client,
        [request],
        port,
        dry_run,
        confirmation_token,
        "set_floor_surface_backgrounds",
        planner_override=_plan,
        dispatcher_override=_dispatch,
        completion_note=(
            "No project was saved. RGB is a snapshot, not an automatic surface-color link. "
            "Inspect receipt before any retry."
        ),
    )
