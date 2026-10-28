"""Authorized edit-task checkpoints: verified backups, stable working PLN name."""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path
from uuid import uuid4
from weakref import WeakKeyDictionary

from archicad_mcp_aberto.connection import ArchicadError, resolve_port
from archicad_mcp_aberto.tools import grids, project_save, write

_tasks: WeakKeyDictionary = WeakKeyDictionary()
_settle_pause = asyncio.sleep


class FinishRequest(write.InputModel):
    task_token: str


def _identity(context):
    return tuple(context[key] for key in ("sessionId", "projectEpoch", "projectPath"))


async def _settled_context(client, port):
    """Wait for deferred view updates, without accepting a project/session change."""
    first = previous = await project_save._context(client, port)
    matches = 0
    for _ in range(12):
        await _settle_pause(0.15)
        current = await project_save._context(client, port)
        if _identity(current) != _identity(first):
            raise ValueError("Project/session changed while waiting for view updates.")
        matches = matches + 1 if current == previous else 0
        if matches >= 2:
            return current
        previous = current
    raise ValueError("Project changes have not settled; no write dispatched.")


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy_verified(source: Path, destination: Path) -> dict:
    project_save._path(str(source))
    project_save._path(str(destination))
    before = project_save._fingerprint(source)
    if not before or before["size"] <= 0:
        raise ValueError("Cannot back up an empty or missing working PLN.")
    destination.parent.mkdir(exist_ok=True)
    project_save._path(str(destination))
    partial = destination.with_suffix(".pln.partial")
    digest = hashlib.sha256()
    with source.open("rb") as src, partial.open("xb") as dst:
        for block in iter(lambda: src.read(1024 * 1024), b""):
            dst.write(block)
            digest.update(block)
        dst.flush()
        os.fsync(dst.fileno())
    if (
        project_save._fingerprint(source) != before
        or _hash(source) != digest.hexdigest()
        or _hash(partial) != digest.hexdigest()
    ):
        raise ValueError(
            "Working PLN changed during backup; partial copy preserved for inspection."
        )
    project_save._move_no_replace(partial, destination)
    return {
        "path": str(destination),
        "sha256": digest.hexdigest(),
        "size": destination.stat().st_size,
        "verified": True,
    }


async def _checkpoint_plan(client, requests, port, operation):
    port = await resolve_port(client, port)
    context = await _settled_context(client, port)
    source = project_save._path(context["projectPath"])
    if context["untitled"]:
        raise ValueError("An established working PLN path is needed for same-file saving.")
    current = project_save._fingerprint(source)
    if not current or current["size"] == 0:
        raise ValueError("Working PLN is missing or empty.")
    folder = source.parent / "Anteriores"
    stamp = context["modificationStamp"]
    disk = project_save._archive_path(source.with_name(f"{source.stem}_backup_{stamp}.pln"), folder)
    model = project_save._archive_path(
        source.with_name(f"{source.stem}_backup_estado_{stamp}.pln"), folder
    )
    for path in (disk, model):
        project_save._path(str(path))
    return {
        "operation": operation,
        "target": {"port": port, "project": context},
        "items": [
            {
                "index": 0,
                "status": "ready",
                "source_path": str(source),
                "disk_backup": str(disk),
                "model_backup": str(model),
                "before_file": current,
            }
        ],
        "note": "Standing task authorization covers this internal checkpoint. "
        "No manual Save As or test-project requirement. Keep working filename.",
    }


async def _save_current(client, port, context):
    await grids._addon(
        client,
        port,
        "SaveCurrentProjectPLN",
        {"destinationPath": context["projectPath"], **context},
        write.write_timeout(),
    )
    after = await project_save._context(client, port)
    if _identity(after) != _identity(context):
        raise ValueError(
            "Saved project/session identity changed; inspect before any further write."
        )
    path = project_save._path(after["projectPath"])
    file = project_save._fingerprint(path)
    if not file or file["size"] <= 0:
        raise ValueError("Current working PLN save could not be verified.")
    return after, file


async def _checkpoint_dispatch(client, receipt):
    item = receipt["items"][0]
    context, port = receipt["target"]["project"], receipt["target"]["port"]
    source = project_save._path(item["source_path"])
    try:
        if project_save._fingerprint(source) != item["before_file"]:
            raise ValueError("Disk PLN changed after preview; no model edit authorized yet.")
        item["disk_backup_proof"] = _copy_verified(source, Path(item["disk_backup"]))
        # Preserve the disk baseline BEFORE consolidating pending in-memory edits.
        item["stage"] = "checkpoint_save_dispatched"
        after, file = await _save_current(client, port, context)
        item["stage"] = "checkpoint_saved"
        item["checkpoint_context"] = after
        if _hash(source) == item["disk_backup_proof"]["sha256"]:
            proof = item["disk_backup_proof"]
        else:
            proof = _copy_verified(source, Path(item["model_backup"]))
        item.update(status="verified", stage="checkpoint_verified", backup=proof)
        task_token = str(uuid4())
        _tasks.setdefault(client, {})[task_token] = {
            "client_session": client.session_id,
            "port": port,
            "project": after,
            "file": file,
            "backup": proof,
            "finish_attempted": False,
            "checkpoint_receipt": receipt["receipt_id"],
        }
        receipt["task_token"] = task_token
    except (ArchicadError, OSError, ValueError) as exc:
        unknown = item.get("stage") == "checkpoint_save_dispatched"
        item.update(status="unknown" if unknown else "failed", error=str(exc))
        if isinstance(exc, ArchicadError):
            item.update(error_code=exc.code, error_detail=exc.detail)
        receipt["warning"] = (
            "No task edits may proceed. Preserve backups; "
            "inspect any unknown save without retrying."
        )


async def begin_model_task(
    client, port: int | None = None, dry_run: bool = True, confirmation_token: str | None = None
):
    """Checkpoint once before authorized model edits; retain the working filename."""
    return await write._write(
        client,
        [],
        port,
        dry_run,
        confirmation_token,
        "begin_model_task",
        planner_override=_checkpoint_plan,
        dispatcher_override=_checkpoint_dispatch,
        completion_note=(
            "Task checkpoint. Proceed only if verified; "
            "backup/save needs no repeated user approval."
        ),
    )


def _task(client, token, port):
    task = _tasks.get(client, {}).get(token)
    if (
        not task
        or task["client_session"] != client.session_id
        or task["port"] != port
        or task["finish_attempted"]
    ):
        raise ValueError("Task checkpoint missing, wrong session/port or finish already attempted.")
    backup = project_save._path(task["backup"]["path"])
    if not backup.is_file() or _hash(backup) != task["backup"]["sha256"]:
        raise ValueError("Verified pre-task backup is missing or changed.")
    return task


async def _finish_plan(client, requests, port, operation):
    (request,) = requests
    port = await resolve_port(client, port)
    task = _task(client, request.task_token, port)
    context = await _settled_context(client, port)
    if _identity(context) != _identity(task["project"]):
        raise ValueError("A different project/session is open; do not save this task there.")
    file = project_save._fingerprint(Path(context["projectPath"]))
    if file != task["file"]:
        raise ValueError(
            "Working PLN changed on disk outside this task; inspect before overwriting."
        )
    return {
        "operation": operation,
        "target": {"port": port, "project": context},
        "items": [
            {
                "index": 0,
                "status": "ready",
                "task_token": request.task_token,
                "working_path": context["projectPath"],
                "backup": task["backup"],
            }
        ],
    }


async def _finish_dispatch(client, receipt):
    item, port = receipt["items"][0], receipt["target"]["port"]
    task = _task(client, item["task_token"], port)
    task["finish_attempted"] = True  # A new token must not bypass an uncertain final save.
    try:
        after, file = await _save_current(client, port, receipt["target"]["project"])
        item.update(status="verified", after=after, saved_file=file)
        task["saved"] = True
    except (ArchicadError, OSError, ValueError) as exc:
        item.update(status="unknown", error=str(exc))
        if isinstance(exc, ArchicadError):
            item.update(error_code=exc.code, error_detail=exc.detail)
        receipt["warning"] = (
            "Final save outcome needs inspection; task backup remains preserved. "
            "Never retry blindly."
        )


async def finish_model_task(
    client,
    task_token: str,
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
):
    """Save an authorized editing task to the SAME PLN after its verified checkpoint."""
    return await write._write(
        client,
        [FinishRequest(task_token=task_token)],
        port,
        dry_run,
        confirmation_token,
        "finish_model_task",
        planner_override=_finish_plan,
        dispatcher_override=_finish_dispatch,
        completion_note=(
            "Task result saved to the same working PLN only when verified; "
            "pre-task backup preserved."
        ),
    )
