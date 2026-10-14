"""Project info fields (File > Info > Project Info), through Tapir 1.7.0.

These are the values title blocks show through autotext: project name, client, site and
the rest. set_project_info_fields uses the shared preview, single-use token and receipts,
writes one field at a time and reads every field back. Never saves.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError, TapirError, resolve_port
from archicad_mcp_aberto.tools import write

MAX_CHANGES = 30
# Fields that SetProjectInfoField accepts but Archicad keeps empty (live, AC30 build 3001
# BRA, 14/10/2026): the full name seems to be built from the given and family names.
READ_ONLY = {"CLIENT_FULLNAME": "set CLIENT_GIVENNAME and CLIENT_FAMILYNAME instead"}


async def _fields(client, port, timeout=None) -> list[dict]:
    extra = {} if timeout is None else {"timeout": timeout}
    response = await client.tapir(port, "GetProjectInfoFields", **extra)
    rows = response.get("fields")
    if not isinstance(rows, list):
        raise ValueError("Unexpected project info response.")
    return [r for r in rows if isinstance(r, dict) and isinstance(r.get("projectInfoId"), str)]


async def get_project_info_fields(client: ArchicadClient, port: int | None = None) -> dict:
    port = await resolve_port(client, port)
    fields = await _fields(client, port)
    return {"port": port, "total": len(fields), "fields": fields}


class ProjectInfoChange(write.InputModel):
    field: Annotated[str, Field(min_length=1, max_length=255)]
    value: Annotated[str, Field(max_length=10000)]


def _pick(rows: list[dict], wanted: str) -> dict:
    exact = [r for r in rows if r["projectInfoId"] == wanted]
    if exact:
        return exact[0]
    key = wanted.strip().casefold()
    found = [r for r in rows if str(r.get("projectInfoName", "")).casefold() == key]
    if len(found) != 1:
        problem = "is ambiguous; pass its id" if found else "does not exist"
        raise ValueError(f"Project info field {wanted!r} {problem}.")
    return found[0]


async def _plan(client, changes, port, operation):
    port, target, _ = await write._context(client, port)
    rows = await _fields(client, port)
    items, seen = [], set()
    for index, change in enumerate(changes):
        try:
            row = _pick(rows, change.field)
        except ValueError as exc:
            raise ValueError(f"Change {index}: {exc}") from None
        if row["projectInfoId"] in READ_ONLY:
            raise ValueError(
                f"Change {index}: Archicad does not keep {row['projectInfoId']} when written; "
                f"{READ_ONLY[row['projectInfoId']]}."
            )
        if row["projectInfoId"] in seen:
            raise ValueError(f"Change {index}: field {row['projectInfoId']} appears twice.")
        seen.add(row["projectInfoId"])
        items.append(
            {
                "index": index,
                "status": "ready",
                "field_id": row["projectInfoId"],
                "field_name": row.get("projectInfoName"),
                "before": row.get("projectInfoValue"),
                "unchanged": row.get("projectInfoValue") == change.value,
                "parameters": {
                    "projectInfoId": row["projectInfoId"],
                    "projectInfoValue": change.value,
                },
            }
        )
    return {"operation": operation, "target": target, "items": items}


async def _dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    written = []
    for position, item in enumerate(items):
        try:
            item["write_response"] = await client.tapir(
                port, "SetProjectInfoField", item["parameters"], timeout=timeout
            )
        except TapirError as exc:
            if exc.detail:  # Tapir answered with its own error: this field was not set.
                item.update(status="failed", error=exc.detail)
                continue
            for later in items[position:]:
                later.update(status="unknown", error=str(exc))
            receipt["warning"] = "Outcome is unknown. Inspect Archicad; do not retry this plan."
            break
        except ArchicadError as exc:
            # A lost answer leaves this field and every later one unknown; stop writing.
            for later in items[position:]:
                later.update(status="unknown", error=str(exc))
            receipt["warning"] = "Outcome is unknown. Inspect Archicad; do not retry this plan."
            break
        item["status"] = "unverified"
        written.append(item)
    if not written:
        return
    try:
        rows = {r["projectInfoId"]: r for r in await _fields(client, port, timeout)}
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    for item in written:
        row: Any = rows.get(item["field_id"])
        item["after"] = row.get("projectInfoValue") if isinstance(row, dict) else None
        ok = item["after"] == item["parameters"]["projectInfoValue"]
        item["status"] = "verified" if ok else "verification_failed"
        if not ok:
            item["mismatches"] = ["projectInfoValue"]


async def set_project_info_fields(
    client: ArchicadClient,
    changes: list[dict | ProjectInfoChange],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 30 project info values; an empty value clears the field."""
    if not 1 <= len(changes) <= MAX_CHANGES:
        raise ValueError(f"Pass between 1 and {MAX_CHANGES} changes.")
    validated = [
        c if isinstance(c, ProjectInfoChange) else ProjectInfoChange.model_validate(c)
        for c in changes
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "set_project_info_fields",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
