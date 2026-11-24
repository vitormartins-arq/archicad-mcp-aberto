"""Experimental same-path save then project close; never quits/kills an application."""

from __future__ import annotations

from archicad_mcp_aberto.connection import ArchicadError, resolve_port
from archicad_mcp_aberto.tools import grids, model_tasks, project_save, write


class CloseRequest(write.InputModel):
    pass


async def _plan(client, requests, port, operation):
    # Preserve the common multi-instance refusal, but never infer a close target even
    # when discovery finds only one instance.
    requested_port = port
    port = await resolve_port(client, port)
    if requested_port is None:
        raise ValueError("An explicit Archicad port is required even for a close preview.")
    for name in ("PrepareProjectClose", "ClosePreparedProject"):
        available = await client.command(
            port,
            "IsAddOnCommandAvailable",
            {
                "addOnCommandId": {"commandNamespace": "ArchicadMcpAberto", "commandName": name},
            },
        )
        if available.get("isAvailable") is not True:
            raise ValueError("Project-close commands unavailable; update the companion add-on.")
    context = await project_save._context(client, port)
    if context["untitled"]:
        raise ValueError("Save the untitled project to a PLN before requesting close.")
    path = project_save._path(context["projectPath"])
    file = project_save._fingerprint(path)
    if not file or file["size"] <= 0:
        raise ValueError("Current standalone PLN must exist and be nonempty.")
    return {
        "operation": operation,
        "target": {"port": port, "project": context},
        "items": [{"index": 0, "status": "ready", "path": str(path), "before_file": file}],
        "warnings": [
            "Experimental native Close API; live acceptance pending. "
            "Saves the same PLN, no new revision. Closes the project, not the process."
        ],
    }


async def _dispatch(client, receipt):
    item = receipt["items"][0]
    port = receipt["target"]["port"]
    context = receipt["target"]["project"]
    phase = "precondition"
    item.update(status="unknown", save_verified=False, close_dispatched=False, close_verified=False)
    try:
        path = project_save._path(item["path"])
        if project_save._fingerprint(path) != item["before_file"]:
            raise ValueError("PLN changed before save; nothing dispatched.")
        phase = "save"
        saved = await grids._addon(
            client,
            port,
            "PrepareProjectClose",
            {
                **context,
                "destinationPath": str(path),
            },
            timeout=receipt["write_timeout_seconds"],
        )
        phase = "save_verification"
        actual = await project_save._context(client, port)
        if any(actual[k] != saved.get(k) for k in actual):
            raise ValueError("Native save and context read-back disagree; not closing.")
        if any(actual[k] != context[k] for k in ("sessionId", "projectEpoch", "projectPath")):
            raise ValueError("Project identity changed during save; not closing.")
        file = project_save._fingerprint(path)
        if not file or file["size"] <= 0 or str(file["size"]) != saved.get("savedFileSize"):
            raise ValueError("Saved PLN size not verified; not closing.")
        token = saved.get("closeToken")
        if not isinstance(token, str) or not token:
            raise ValueError("Native close proof missing; not closing.")
        digest = model_tasks._hash(path)
        if (
            project_save._fingerprint(path) != file
            or await project_save._context(client, port) != actual
        ):
            raise ValueError("File or project changed during verification; not closing.")
        item.update(save_verified=True, saved_file=file, saved_sha256=digest, saved_context=actual)
        # Persist successful save proof before a close can disconnect the endpoint.
        receipt["saved_receipt_path"] = write._journal(receipt, "saved")
        phase = "close"
        item["close_dispatched"] = True
        result = await grids._addon(
            client,
            port,
            "ClosePreparedProject",
            {
                **{
                    k: actual[k]
                    for k in ("sessionId", "projectEpoch", "projectPath", "modificationStamp")
                },
                "closeToken": token,
            },
            timeout=receipt["write_timeout_seconds"],
        )
        item["native_close"] = result
        if result.get("closeReturnedNoError") is True and result.get("noOpenProject") is True:
            item.update(status="verified", close_verified=True)
        else:
            item.update(
                status="verification_failed",
                error="Native close read-back did not confirm no open project.",
            )
    except (ArchicadError, OSError, ValueError) as exc:
        item.update(
            status="unknown" if phase in ("save", "close") else "verification_failed",
            phase=phase,
            error=str(exc),
        )
        receipt["warning"] = (
            "Inspect this receipt; never retry an uncertain save/close automatically."
        )


async def save_and_close_project(client, port=None, dry_run=True, confirmation_token=None):
    """Preview/apply one exact saved project, without keyboard/mouse or process termination."""
    return await write._write(
        client,
        [CloseRequest()],
        port,
        dry_run,
        confirmation_token,
        "save_and_close_project",
        planner_override=_plan,
        dispatcher_override=_dispatch,
        completion_note="Same-path save and project close only when verified in the receipt. "
        "No revision/archive move, no application quit, no automatic retry or Undo.",
    )
