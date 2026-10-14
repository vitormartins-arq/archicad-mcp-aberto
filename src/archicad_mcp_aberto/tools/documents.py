"""New independent worksheets, details and layouts (Tapir 1.7.0).

create_worksheets and create_details add empty independent Worksheet and Detail
viewpoints to the Project Map; create_layouts adds layouts to the Layout Book on an
existing master layout. Tapir's CreateLayout would create a missing master layout by
name, so the MCP always sends the master's navigator ID and refuses a master that does
not exist. All three use the shared preview, single-use token and receipts, and find each
new database back in the Navigator (GetNavigatorItemTree, GetDatabaseIdFromNavigatorItemId).
Never saves.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError, TapirError
from archicad_mcp_aberto.tools import write

MAX_ITEMS = 20
Text = Annotated[str, Field(min_length=1, max_length=255)]
# operation -> (Tapir command, list key, navigator map, navigator item type)
KINDS = {
    "create_worksheets": (
        "CreateWorksheets",
        "worksheetsData",
        "ProjectMap",
        "WorksheetDrawingItem",
    ),
    "create_details": ("CreateDetails", "detailsData", "ProjectMap", "DetailDrawingItem"),
    "create_layouts": ("CreateLayout", "layoutsData", "LayoutBook", "LayoutItem"),
}


def _guid(value: Any) -> str | None:
    guid = value.get("guid") if isinstance(value, dict) else None
    try:
        return str(UUID(guid)).upper()
    except (TypeError, ValueError, AttributeError):
        return None


def _trimmed(value: str) -> str:
    if value != value.strip():
        raise ValueError("must not start or end with spaces.")
    return value


class ViewpointCreate(write.InputModel):
    name: Text
    reference_id: Text

    @field_validator("name", "reference_id")
    @classmethod
    def trimmed(cls, value: str) -> str:
        return _trimmed(value)


class LayoutCreate(write.InputModel):
    name: Text
    master: Text

    @field_validator("name")
    @classmethod
    def trimmed(cls, value: str) -> str:
        return _trimmed(value)


def _flatten(node: Any, out: list[dict]) -> list[dict]:
    if not isinstance(node, dict):
        return out
    guid = _guid(node.get("navigatorItemId"))
    if guid:
        out.append(
            {
                "navigator_guid": guid,
                "type": node.get("type"),
                "name": node.get("name"),
                "uiId": node.get("uiId"),
            }
        )
    for child in node.get("children", []) if isinstance(node.get("children"), list) else []:
        _flatten(child.get("navigatorItem") if isinstance(child, dict) else None, out)
    return out


async def _tree(client, port, map_id, timeout=None) -> list[dict]:
    extra = {} if timeout is None else {"timeout": timeout}
    response = await client.tapir(port, "GetNavigatorItemTree", {"navigatorMapId": map_id}, **extra)
    root = response.get("navigatorItemTree")
    if not isinstance(root, dict):
        raise ValueError(f"Unexpected {map_id} navigator response.")
    return _flatten(root, [])


async def _databases(client, port, nav_guids, timeout=None) -> dict[str, str | None]:
    if not nav_guids:
        return {}
    extra = {} if timeout is None else {"timeout": timeout}
    response = await client.tapir(
        port,
        "GetDatabaseIdFromNavigatorItemId",
        {"navigatorItemIds": [{"navigatorItemId": {"guid": g}} for g in nav_guids]},
        **extra,
    )
    rows = response.get("databases")
    if not isinstance(rows, list) or len(rows) != len(nav_guids):
        raise ValueError("Unexpected database ID response cardinality.")
    return {
        nav: _guid(row.get("databaseId")) if isinstance(row, dict) else None
        for nav, row in zip(nav_guids, rows, strict=True)
    }


async def _plan(client, entries, port, operation):
    port, target, _ = await write._context(client, port)
    _, _, map_id, item_type = KINDS[operation]
    tree = await _tree(client, port, map_id)
    same = [r for r in tree if r["type"] == item_type]
    masters = [r for r in tree if r["type"] == "MasterLayoutItem"]
    seen, items = set(), []
    for index, entry in enumerate(entries):
        if operation == "create_layouts":
            key: tuple = (entry.name.casefold(),)
            clash = [r for r in same if str(r["name"]).casefold() == key[0]]
            found = [r for r in masters if str(r["name"]).casefold() == entry.master.casefold()]
            exact = [r for r in found if r["name"] == entry.master]
            found = exact if len(exact) == 1 else found
            if len(found) != 1:
                problem = "is ambiguous" if found else "does not exist (create it in Archicad)"
                raise ValueError(f"Layout {index}: master layout {entry.master!r} {problem}.")
            parameters = {
                "masterNavigatorItemId": {"guid": found[0]["navigator_guid"]},
                "layoutName": entry.name,
            }
            extra = {"master_name": found[0]["name"], "master_guid": found[0]["navigator_guid"]}
        else:
            key = (entry.reference_id.casefold(), entry.name.casefold())
            clash = [
                r for r in same if (str(r["uiId"]).casefold(), str(r["name"]).casefold()) == key
            ]
            parameters = {"name": entry.name, "referenceId": entry.reference_id}
            extra = {"reference_id": entry.reference_id}
        if clash:
            raise ValueError(f"Item {index}: {entry.name!r} already exists in the Navigator.")
        if key in seen:
            raise ValueError(f"Item {index}: {entry.name!r} appears twice.")
        seen.add(key)
        items.append(
            {
                "index": index,
                "status": "ready",
                "name": entry.name,
                **extra,
                "parameters": parameters,
            }
        )
    return {"operation": operation, "target": target, "items": items}


async def _dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    command, list_key, map_id, item_type = KINDS[receipt["operation"]]
    try:
        raw = await client.tapir(
            port, command, {list_key: [i["parameters"] for i in items]}, timeout=timeout
        )
    except TapirError as exc:
        status = "failed" if exc.detail else "unknown"
        for item in items:
            item.update(status=status, error=exc.detail or str(exc))
        if not exc.detail:
            receipt["warning"] = "Outcome is unknown. Inspect Archicad; do not retry this plan."
        return
    except ArchicadError as exc:
        for item in items:
            item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Outcome is unknown. Inspect Archicad; do not retry this plan."
        return
    receipt["raw_response"] = raw
    rows = raw.get("databases")
    if not isinstance(rows, list) or len(rows) != len(items):
        for item in items:
            item.update(status="unknown", error="Unexpected response cardinality.")
        return
    created = []
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        guid = _guid(row.get("databaseId")) if isinstance(row, dict) else None
        if isinstance(row, dict) and "error" in row:
            item.update(status="failed", error=row["error"])
        elif guid:
            item.update(status="unverified", database_guid=guid)
            created.append(item)
        else:
            item.update(status="unknown", error="Missing database ID or error; inspect Archicad.")
    if not created:
        return
    try:
        rows = [r for r in await _tree(client, port, map_id, timeout) if r["type"] == item_type]
        databases = await _databases(client, port, [r["navigator_guid"] for r in rows], timeout)
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    by_database = {databases.get(r["navigator_guid"]): r for r in rows}
    for item in created:
        row = by_database.get(item["database_guid"])
        item["after"] = row
        problems = ["missing"] if row is None else []
        if row is not None and row["name"] != item["name"]:
            problems.append("name")
        if row is not None and "reference_id" in item and row["uiId"] != item["reference_id"]:
            problems.append("reference_id")
        item["status"] = "verification_failed" if problems else "verified"
        if problems:
            item["mismatches"] = problems
        else:
            item["navigator_guid"] = row["navigator_guid"]


async def _run(client, entries, model, port, dry_run, token, operation) -> dict:
    if not 1 <= len(entries) <= MAX_ITEMS:
        raise ValueError(f"Pass between 1 and {MAX_ITEMS} items.")
    validated = [e if isinstance(e, model) else model.model_validate(e) for e in entries]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        token,
        operation,
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )


async def create_worksheets(
    client: ArchicadClient,
    worksheets: list[dict | ViewpointCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 empty independent worksheets (name, reference_id)."""
    return await _run(
        client, worksheets, ViewpointCreate, port, dry_run, confirmation_token, "create_worksheets"
    )


async def create_details(
    client: ArchicadClient,
    details: list[dict | ViewpointCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 empty independent details (name, reference_id)."""
    return await _run(
        client, details, ViewpointCreate, port, dry_run, confirmation_token, "create_details"
    )


async def create_layouts(
    client: ArchicadClient,
    layouts: list[dict | LayoutCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 layouts, each on an existing master layout."""
    return await _run(
        client, layouts, LayoutCreate, port, dry_run, confirmation_token, "create_layouts"
    )
