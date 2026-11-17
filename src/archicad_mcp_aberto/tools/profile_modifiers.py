"""Inspect and rename edge-offset modifiers on a complex profile by GUID."""

from __future__ import annotations

import unicodedata
from typing import Annotated
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError, resolve_port
from archicad_mcp_aberto.tools import grids, project_save, write


def _guid(value: str) -> str:
    guid = UUID(value)
    if not guid.int:
        raise ValueError("GUID must not be null.")
    return str(guid).upper()


class ModifierRename(write.InputModel):
    modifier_id: str
    new_name: Annotated[str, Field(min_length=1)]

    @field_validator("modifier_id")
    @classmethod
    def modifier_guid(cls, value: str) -> str:
        return _guid(value)

    @field_validator("new_name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if (
            value != value.strip()
            or len(value.encode("utf-16-le")) // 2 >= 256
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
        ):
            raise ValueError(
                "Use a name under 256 UTF-16 units without padding or control characters."
            )
        return value


async def get_profile_modifiers(
    client: ArchicadClient, profile_guid: str, port: int | None = None
) -> dict:
    guid = _guid(profile_guid)
    port = await resolve_port(client, port)
    raw = await grids._addon(client, port, "GetProfileModifiers", {"profileGuid": guid})
    if (
        not isinstance(raw, dict)
        or _guid(raw.get("profileGuid", "")) != guid
        or not isinstance(raw.get("geometryFingerprint"), str)
        or not raw["geometryFingerprint"]
        or not isinstance(raw.get("modifiers"), list)
    ):
        raise ValueError("Invalid profile modifier response.")
    modifiers = []
    seen = set()
    for row in raw["modifiers"]:
        modifier_id = _guid(row["id"])
        if modifier_id in seen or not isinstance(row.get("name"), str):
            raise ValueError("Invalid or repeated modifier in profile response.")
        seen.add(modifier_id)
        modifiers.append({**row, "id": modifier_id})
    return {
        "port": port,
        "profile_guid": guid,
        "geometry_fingerprint": raw["geometryFingerprint"],
        "modifiers": sorted(modifiers, key=lambda row: row["id"]),
    }


def _name_key(name: str) -> str:
    return unicodedata.normalize("NFC", name.strip()).casefold()


async def _plan(client, request, port, operation):
    guid, edits = request
    port = await resolve_port(client, port)
    context = await project_save._context(client, port)
    profile = await get_profile_modifiers(client, guid, port)
    by_id = {m["id"]: m for m in profile["modifiers"]}
    final_names = {key: row["name"] for key, row in by_id.items()}
    items = []
    for edit in edits:
        row = by_id.get(edit.modifier_id)
        if row is None or row.get("renamable") is not True:
            raise ValueError(
                f"Modifier {edit.modifier_id} is not a named edge offset on this profile."
            )
        old_name = row["name"]
        final_names[edit.modifier_id] = edit.new_name
        items.append(
            {
                "status": "ready",
                "parameters": {
                    "id": edit.modifier_id,
                    "oldName": old_name,
                    "newName": edit.new_name,
                },
            }
        )

    for item in items:
        rename = item["parameters"]
        if rename["oldName"] != rename["newName"] and any(
            other != rename["id"] and _name_key(name) == _name_key(rename["newName"])
            for other, name in final_names.items()
        ):
            raise ValueError(f"Target name {rename['newName']!r} belongs to another modifier ID.")

    return {
        "operation": operation,
        "target": {"port": port, "context": context},
        "profile_guid": guid,
        "geometry_fingerprint": profile["geometry_fingerprint"],
        "names_before": {key: row["name"] for key, row in by_id.items()},
        "items": items,
    }


async def _dispatch(client, receipt):
    target = receipt["target"]
    try:
        result = await grids._addon(
            client,
            target["port"],
            "RenameProfileModifiers",
            {
                "profileGuid": receipt["profile_guid"],
                "context": target["context"],
                "geometryFingerprint": receipt["geometry_fingerprint"],
                "renames": [item["parameters"] for item in receipt["items"]],
            },
            timeout=receipt["write_timeout_seconds"],
        )
        receipt["raw_response"] = result
        status = {"verified": "verified", "restored": "verification_failed"}.get(
            result.get("status") if isinstance(result, dict) else None, "unknown"
        )
    except ArchicadError as exc:
        receipt["error"] = str(exc)
        status = "unknown"
    for item in receipt["items"]:
        item["status"] = status
    if status == "unknown":
        receipt["warning"] = (
            "Inspect the profile before preparing a new plan. Do not retry this write."
        )


async def rename_profile_modifiers(
    client: ArchicadClient,
    profile_guid: str,
    renames: list[dict | ModifierRename],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    if not 1 <= len(renames) <= 100:
        raise ValueError("Pass between 1 and 100 modifier renames for one profile.")
    edits = [ModifierRename.model_validate(row) for row in renames]
    if len({edit.modifier_id for edit in edits}) != len(edits):
        raise ValueError("Modifier IDs must be unique in the batch.")
    return await write._write(
        client,
        (_guid(profile_guid), edits),
        port,
        dry_run,
        confirmation_token,
        "rename_profile_modifiers",
        planner_override=_plan,
        dispatcher_override=_dispatch,
        completion_note="Check the native verification result before saving this project.",
    )
