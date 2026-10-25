"""Replace standalone Object library parts without deleting instances.

Mount points are explicit, in metres in each final-sized object's local axes, before
reflection/rotation. They are never inferred from a bounding box. GDL parameters other
than A/B/ZZYZX intentionally take target defaults; the preview discloses both memos.
"""

from __future__ import annotations

import math
from typing import Annotated
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadError, resolve_port
from archicad_mcp_aberto.tools import edit, grids, write


class MountPoint(write.InputModel):
    x: float
    y: float
    z: float


class Replacement(write.InputModel):
    guid: str
    target_unid: Annotated[str, Field(min_length=1, max_length=127)]
    source_mount: MountPoint
    target_mount: MountPoint

    @field_validator("guid")
    @classmethod
    def guid_value(cls, value):
        return str(UUID(value)).upper()


def _vector(point: dict, angle: float, reflected: bool) -> dict:
    # GDL reflection reverses local X (mirror plane YZ), then rotates about Z.
    x, y = (-point["x"] if reflected else point["x"]), point["y"]
    c, s = math.cos(angle), math.sin(angle)
    return {"x": c * x - s * y, "y": s * x + c * y, "z": point["z"]}


def _placement(before: dict, source: dict, target: dict) -> tuple[dict, dict]:
    old = _vector(source, before["angle"], before["reflected"])
    new = _vector(target, before["angle"], before["reflected"])
    mount = {
        "x": before["x"] + old["x"],
        "y": before["y"] + old["y"],
        "z": before["level"] + old["z"],
    }
    placement = {
        "x": mount["x"] - new["x"],
        "y": mount["y"] - new["y"],
        "level": mount["z"] - new["z"],
    }
    if not all(math.isfinite(v) for v in (*mount.values(), *placement.values())):
        raise ValueError("Mount transformation overflowed.")
    return placement, mount


async def _data(client, port, guids, unid, timeout=None):
    result = await grids._addon(
        client, port, "GetObjectReplacementData", {"guids": guids, "targetUnid": unid}, timeout
    )
    if not isinstance(result.get("objects"), list) or len(result["objects"]) != len(guids):
        raise ValueError("Unexpected object replacement snapshot cardinality.")
    if not result.get("sessionId") or not isinstance(result.get("target"), dict):
        raise ValueError("Missing native session/library identity.")
    if any(not isinstance(r, dict) or "error" in r for r in result["objects"]):
        raise ValueError("One or more instances are not readable standalone Objects.")
    return result


async def inspect_object_replacements(
    client, guids: list[str], target_unid: str, port: int | None = None
) -> dict:
    """Read actual library/transform after an unknown result before planning a new write."""
    canonical = [str(UUID(g)).upper() for g in guids]
    edit._unique(canonical, 50)
    port = await resolve_port(client, port)
    return {"port": port, **await _data(client, port, canonical, target_unid)}


async def _plan(client, replacements, port, operation):
    guids = [r.guid for r in replacements]
    port, context, _ = await edit._editable(client, guids, port)
    unids = {r.target_unid for r in replacements}
    if len(unids) != 1:
        raise ValueError("Use one exact target library ID per batch; ambiguous mapping refused.")
    data = await _data(client, port, guids, next(iter(unids)))
    target = data["target"]
    items = []
    for index, (request, before) in enumerate(zip(replacements, data["objects"], strict=True)):
        if str(UUID(before["guid"])).upper() != request.guid:
            raise ValueError("Native snapshot order/identity mismatch.")
        for key in ("a", "b", "height"):
            if not all(
                isinstance(r.get(key), int | float) and math.isfinite(r[key]) and r[key] > 0
                for r in (before, target)
            ):
                raise ValueError(f"Readable positive {key} required on source and target.")
        placement, mount = _placement(
            before, request.source_mount.model_dump(), request.target_mount.model_dump()
        )
        items.append(
            {
                "index": index,
                "status": "ready",
                "element_guid": request.guid,
                "before": before,
                "destination": target,
                "source_mount": request.source_mount.model_dump(),
                "target_mount": request.target_mount.model_dump(),
                "mount_story_coordinates": mount,
                "parameters": {
                    "guid": request.guid,
                    "stamp": before["stamp"],
                    **placement,
                    **{k: before[k] for k in ("a", "b", "height")},
                },
            }
        )
    return {
        "operation": operation,
        "target": context,
        "native_session": data["sessionId"],
        "library": target,
        "items": items,
        "limitations": [
            "A/B/ZZYZX dimensions, angle, reflection and home story are preserved.",
            "Other GDL parameters take the displayed target defaults, including arrays.",
            "The anchor hotspot resets to the object origin; offset resets to zero.",
            "GUID/layer/groups/classifications are checked after writing. "
            "Properties and associations are not explicitly written; "
            "their preservation needs live certification.",
            "Mount coordinates are explicit final-sized local metres; no geometry/box inference.",
        ],
    }


def _mismatches(item, after):
    if not isinstance(after, dict) or "error" in after:
        return ["Missing object readback."]
    before, expected = item["before"], item["parameters"]
    problems = []
    if str(UUID(after.get("guid", ""))).upper() != item["element_guid"]:
        problems.append("GUID changed.")
    if (after.get("library") or {}).get("unid") != item["destination"]["unid"]:
        problems.append("Library unique ID differs.")
    for key in ("floorIndex", "layerIndex", "reflected", "groupGuid", "groupReadCode"):
        if after.get(key) != before[key]:
            problems.append(f"{key} changed.")

    def classification_key(rows):
        return sorted((r["system"], r["item"]) for r in rows)

    if classification_key(after.get("classifications", [])) != classification_key(
        before.get("classifications", [])
    ):
        problems.append("Classifications changed.")
    if after.get("fixPoint") != -1 or after.get("offsetX") != 0 or after.get("offsetY") != 0:
        problems.append("Target origin anchor/offset differs.")
    for key, value in {
        **{k: expected[k] for k in ("x", "y", "level", "a", "b", "height")},
        "angle": before["angle"],
    }.items():
        actual = after.get(key)
        if not isinstance(actual, int | float) or not math.isclose(
            actual, value, abs_tol=1e-6, rel_tol=0
        ):
            problems.append(f"{key} differs.")
    if not problems:
        _, mount = _placement(after, item["target_mount"], item["target_mount"])
        if any(
            not math.isclose(mount[k], item["mount_story_coordinates"][k], abs_tol=1e-6, rel_tol=0)
            for k in mount
        ):
            problems.append("Explicit mount reference moved.")
    return problems


async def _dispatch(client, receipt):
    port = receipt["target"]["port"]
    items = receipt["items"]
    try:
        await grids._addon(
            client,
            port,
            "ReplaceObjectLibraries",
            {
                "sessionId": receipt["native_session"],
                "targetUnid": receipt["library"]["unid"],
                "targetIndex": receipt["library"]["index"],
                "objects": [item["parameters"] for item in items],
            },
            receipt["write_timeout_seconds"],
        )
    except ArchicadError as exc:
        # A transport/native error is never evidence that no mutation happened.
        for item in items:
            item.update(status="unknown", error=str(exc))
        receipt["warning"] = (
            "Consult the write receipt and read object state before any new write. "
            "Never retry this token."
        )
        return
    for item in items:
        item["status"] = "unverified"
    try:
        data = await _data(
            client,
            port,
            [i["element_guid"] for i in items],
            receipt["library"]["unid"],
            receipt["write_timeout_seconds"],
        )
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    for item, after in zip(items, data["objects"], strict=True):
        item["after"] = after
        problems = _mismatches(item, after)
        item["status"] = "verification_failed" if problems else "verified"
        if problems:
            item["mismatches"] = problems


async def replace_object_libraries(
    client,
    replacements: list[dict | Replacement],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/confirm one target library per batch. Never imports, deletes or saves."""
    validated = [
        r if isinstance(r, Replacement) else Replacement.model_validate(r) for r in replacements
    ]
    edit._unique([r.guid for r in validated], 50)
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "replace_object_libraries",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
