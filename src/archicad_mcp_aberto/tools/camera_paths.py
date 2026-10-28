"""Physical cameras from saved views, with task backup and stable-path saving."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4
from weakref import WeakKeyDictionary

from archicad_mcp_aberto.connection import ArchicadError, resolve_port
from archicad_mcp_aberto.tools import grids, model_tasks, navigator, project_save, write


@dataclass
class _State:
    session: object
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    previews: dict = field(default_factory=dict)


_states: WeakKeyDictionary = WeakKeyDictionary()


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sources_signature(rows):
    return _canonical(
        [{**row, "representationJSON": json.loads(row["representationJSON"])} for row in rows]
    )


async def list_camera_paths(client, port: int | None = None):
    port = await resolve_port(client, port)
    raw = await grids._addon(client, port, "GetCameraPaths")
    return {"port": port, **raw}


async def _ordered_views(client, port, guids):
    rows = await navigator._view_tree(client, port, "PublicViewMap", write.write_timeout())
    supported = [
        r
        for r in rows
        if r["type"].casefold().removesuffix("item") in {"perspective", "axonometry"}
    ]
    if guids is not None:
        if not guids:
            raise ValueError(
                "Give at least one view GUID, or omit the list for all saved 3D views."
            )
        wanted = [str(UUID(guid)).upper() for guid in guids]
        if len(set(wanted)) != len(wanted):
            raise ValueError("Duplicate source view GUIDs are refused.")
        supported = [row for row in supported if row["guid"] in wanted]
        if {r["guid"] for r in supported} != set(wanted):
            raise ValueError("Sources must be saved perspective/axonometric views in the View Map.")
    if not 1 <= len(supported) <= 60:
        raise ValueError("Select 1–60 saved 3D views; 3D documents are not cameras.")
    return supported


def _groups(native, path_name):
    grouped = {}
    skipped = []
    for row in native["views"]:
        if row.get("isPerspective") is not True:
            skipped.append(
                {
                    "guid": row["sourceViewGuid"],
                    "name": row["name"],
                    "reason": "Parallel projection preserved; no perspective substitution.",
                }
            )
            continue
        representation = json.loads(row["representationJSON"])
        key = hashlib.sha256(_canonical(representation).encode()).hexdigest()
        grouped.setdefault(key, []).append(row)
    if not grouped:
        raise ValueError("No perspective source views; parallel views remain untouched.")
    primary = max(grouped, key=lambda key: len(grouped[key]))
    groups = []
    for key, views in grouped.items():
        label = path_name if key == primary else f"{path_name} - {key[:10]}"
        if len(label.encode("utf-16-le")) // 2 > 200:
            raise ValueError("Path name plus representation suffix exceeds 200 UTF-16 units.")
        groups.append(
            {
                "path_name": label,
                "representation_hash": key,
                "views": views,
                "view_guids": [v["sourceViewGuid"] for v in views],
            }
        )
    return groups, skipped


async def _plan(client, port, name, guids):
    rows = await _ordered_views(client, port, guids)
    ordered = [row["guid"] for row in rows]
    native = await grids._addon(
        client,
        port,
        "PrepareCameraPath",
        {
            "pathName": name,
            "viewGuids": ordered,
        },
        write.write_timeout(),
    )
    if native.get("stateRestored") is not True or len(native.get("views", [])) != len(rows):
        raise ValueError("Source capture/restoration was not confirmed; no cameras may be written.")
    if [v["sourceViewGuid"].upper() for v in native["views"]] != ordered:
        raise ValueError("Native source identity/order differs from Navigator.")
    groups, skipped = _groups(native, name)
    context = await project_save._context(client, port)
    if model_tasks._identity(context) != model_tasks._identity(native["context"]):
        raise ValueError("Project changed during source capture.")
    source = project_save._path(context["projectPath"])
    inventory = await grids._addon(client, port, "GetCameraPaths")
    return {
        "target": {"port": port, "project": context},
        "path_name": name,
        "ordered_sources": ordered,
        "groups": groups,
        "skipped": skipped,
        "source_signature": _sources_signature(native["views"]),
        "inventory": inventory,
        "file": project_save._fingerprint(source),
        "note": "Create physical cameras only. Keep different captured representations "
        "in separate paths; no Publisher edits, publication or upload. "
        "Automatic verified backup before edits, save to SAME working PLN after. "
        "Native representation comparisons are not a certification of exported BIMx geometry.",
    }


def _public_plan(plan):
    return {
        "target": plan["target"],
        "path_name": plan["path_name"],
        "groups": [
            {
                "path_name": g["path_name"],
                "representation_hash": g["representation_hash"],
                "views": [
                    {k: v[k] for k in ("sourceViewGuid", "name", "projection")} for v in g["views"]
                ],
            }
            for g in plan["groups"]
        ],
        "skipped": plan["skipped"],
        "note": plan["note"],
    }


async def _checkpoint(client, port):
    preview = await model_tasks.begin_model_task(client, port)
    result = await model_tasks.begin_model_task(client, port, False, preview["confirmation_token"])
    if result["status"] != "verified":
        raise ValueError(
            f"Task backup/checkpoint failed; no camera edits. Receipt: {result.get('receipt_path')}"
        )
    return result


async def _finish(client, token, port):
    preview = await model_tasks.finish_model_task(client, token, port)
    return await model_tasks.finish_model_task(
        client, token, port, False, preview["confirmation_token"]
    )


async def create_camera_paths_from_views(
    client,
    path_name: str = "BIMx - Apresentação",
    view_guids: list[str] | None = None,
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
):
    """Capture saved 3D views, create deduplicated physical Camera/CamSet elements.

    A logical apply checkpoints automatically and saves to the same PLN. Normal user
    work does not require an untitled/test file, manual Save As or another save approval.
    """
    explicit_port = port is not None
    if not dry_run and not explicit_port:
        raise ValueError("An explicit port is required to apply.")
    port = await resolve_port(client, port)
    if (
        not path_name
        or path_name != path_name.strip()
        or any(c in path_name for c in "\x00\r\n")
        or len(path_name.encode("utf-16-le")) // 2 > 180
    ):
        raise ValueError("Give a visible path name up to 180 UTF-16 units.")
    if client.session_id is None:
        raise RuntimeError("ArchicadClient must be entered.")
    state = _states.get(client)
    if not state or state.session != client.session_id:
        state = _State(client.session_id)
        _states[client] = state
    arguments = {"port": port, "path_name": path_name, "view_guids": view_guids}
    async with state.lock:
        if dry_run:
            plan = await _plan(client, port, path_name, view_guids)
            now = time.monotonic()
            state.previews = {k: v for k, v in state.previews.items() if v["expires"] > now}
            if len(state.previews) >= 16:
                raise ValueError("Too many active camera previews.")
            token = str(uuid4())
            state.previews[token] = {
                "arguments": deepcopy(arguments),
                "plan": plan,
                "expires": now + write.PREVIEW_SECONDS,
            }
            return {
                **_public_plan(plan),
                "dry_run": True,
                "confirmation_token": token,
                "expires_in_seconds": write.PREVIEW_SECONDS,
            }
        if not explicit_port:
            raise ValueError("An explicit port is required to apply.")
        entry = state.previews.get(confirmation_token or "")
        if not entry or entry["expires"] <= time.monotonic() or entry["arguments"] != arguments:
            raise ValueError("Camera preview missing/expired/consumed or inputs changed.")
        plan = entry["plan"]
        current = await project_save._context(client, port)
        if current != plan["target"]["project"]:
            raise ValueError(
                "Project/session/stamp changed after preview; create a fresh internal plan."
            )
        if project_save._fingerprint(Path(current["projectPath"])) != plan["file"]:
            raise ValueError("Working PLN changed on disk after preview.")
        if await grids._addon(client, port, "GetCameraPaths") != plan["inventory"]:
            raise ValueError("Camera inventory or display state changed after preview.")
        receipt = {
            **_public_plan(plan),
            "operation": "create_camera_paths_from_views",
            "receipt_id": str(uuid4()),
            "status": "prepared",
            "dry_run": False,
            "paths": [],
            "write_timeout_seconds": write.write_timeout(),
        }
        receipt["prepared_receipt_path"] = write._journal(receipt, "prepared")
        state.previews.pop(confirmation_token)
        try:
            checkpoint = await _checkpoint(client, port)
            receipt["checkpoint"] = checkpoint
            # Checkpoint save may advance the stamp. Re-capture and compare actual
            # sources; never merely ignore staleness after this intentional save.
            refreshed = await _plan(client, port, path_name, view_guids)
            if (
                refreshed["source_signature"] != plan["source_signature"]
                or refreshed["ordered_sources"] != plan["ordered_sources"]
                or refreshed["inventory"] != plan["inventory"]
            ):
                raise ValueError(
                    "Source views/inventory changed during checkpoint; no cameras written."
                )
            for group in refreshed["groups"]:
                native = await grids._addon(
                    client,
                    port,
                    "PrepareCameraPath",
                    {
                        "pathName": group["path_name"],
                        "viewGuids": group["view_guids"],
                    },
                    write.write_timeout(),
                )
                if _sources_signature(native["views"]) != _sources_signature(group["views"]):
                    raise ValueError("Source capture differs before path dispatch.")
                pending = {
                    "path_name": group["path_name"],
                    "status": "dispatching",
                    "nativeToken": native["nativeToken"],
                }
                receipt["paths"].append(pending)
                write._journal(receipt, f"path-{len(receipt['paths'])}-prepared")
                result = await grids._addon(
                    client,
                    port,
                    "ApplyCameraPath",
                    {
                        "nativeToken": native["nativeToken"],
                        "hideInPlan": True,
                    },
                    write.write_timeout(),
                )
                if result.get("verifiedCount") != len(group["views"]):
                    raise ValueError("Native camera count verification failed.")
                pending.update(status="verified", result=result)
                write._journal(receipt, f"path-{len(receipt['paths'])}-result")
            saved = await _finish(client, checkpoint["task_token"], port)
            receipt["save"] = saved
            complete = saved["status"] == "verified" and all(
                p["result"].get("hiddenInPlan") is True for p in receipt["paths"]
            )
            receipt["status"] = "verified" if complete else "needs_review"
        except (ArchicadError, OSError, ValueError) as exc:
            receipt.update(
                status="needs_review",
                error=str(exc),
                warning=(
                    "Inspect receipt, native inventory and backup. "
                    "Never retry an uncertain camera/save token."
                ),
            )
        try:
            receipt["receipt_path"] = write._journal(receipt, "result")
        except OSError as exc:
            receipt["receipt_error"] = str(exc)
        # Do not send the full repeated inventories/ABI blobs back through MCP.
        public = deepcopy(receipt)
        for path in public["paths"]:
            path.pop("nativeToken", None)
            path.get("result", {}).pop("inventory", None)
        return public
