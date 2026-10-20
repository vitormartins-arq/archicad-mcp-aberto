"""Keynotes (Archicad 28 or newer, Tapir 1.7.0): read the tree and add folders and items.

list_keynotes flattens GetKeynoteTree into folders and items with their path of keys.
create_keynote_folders and create_keynote_items only ADD: a key that already exists
anywhere in the keynote tree is refused, so nothing is changed or replaced and every new
entry can be found back by its GUID and key. Folders and items go in an existing parent
folder (by GUID from list_keynotes) or in the root. Never saves.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError, resolve_port
from archicad_mcp_aberto.tools import write

MAX_FOLDERS = 50
MAX_ITEMS = 100
Key = Annotated[str, Field(min_length=1, max_length=255)]
Text = Annotated[str, Field(max_length=10000)]


def _guid(value: Any) -> str | None:
    try:
        return str(UUID(value["guid"])).upper()
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _flatten(response: dict) -> tuple[list[dict], list[dict]]:
    folders_in_root = response.get("foldersInRoot")
    items_in_root = response.get("itemsInRoot")
    if not isinstance(folders_in_root, list) or not isinstance(items_in_root, list):
        raise ValueError("Unexpected keynote tree response.")
    folders: list[dict] = []
    items: list[dict] = []

    def add_items(rows, parent, path):
        for row in rows:
            items.append(
                {
                    "guid": _guid(row.get("keynoteItemId")),
                    "parent_folder_guid": parent,
                    "path": [*path, row.get("key")],
                    **{k: row.get(k) for k in ("key", "title", "description", "reference")},
                }
            )

    def walk(rows, parent, path):
        for row in rows:
            guid = _guid(row.get("keynoteFolderId"))
            here = [*path, row.get("key")]
            folders.append(
                {
                    "guid": guid,
                    "parent_folder_guid": parent,
                    "path": here,
                    **{k: row.get(k) for k in ("key", "title", "reference")},
                }
            )
            walk(row.get("subFolders") or [], guid, here)
            add_items(row.get("items") or [], guid, here)

    walk(folders_in_root, None, [])
    add_items(items_in_root, None, [])
    return folders, items


async def _tree(client, port, timeout=None):
    extra = {} if timeout is None else {"timeout": timeout}
    return _flatten(await client.tapir(port, "GetKeynoteTree", {}, **extra))


async def list_keynotes(client: ArchicadClient, port: int | None = None) -> dict:
    """Keynote folders and items, each with GUID, parent folder GUID and key path."""
    port = await resolve_port(client, port)
    folders, items = await _tree(client, port)
    return {
        "port": port,
        "folder_count": len(folders),
        "item_count": len(items),
        "folders": folders,
        "items": items,
    }


class _Entry(write.InputModel):
    parent_folder_guid: str | None = None
    key: Key

    @field_validator("parent_folder_guid")
    @classmethod
    def canonical_guid(cls, value: str | None) -> str | None:
        return None if value is None else str(UUID(value)).upper()

    @field_validator("key")
    @classmethod
    def trimmed(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("must not start or end with spaces.")
        return value


class KeynoteFolderCreate(_Entry):
    title: Text


class KeynoteItemCreate(_Entry):
    title: Text | None = None
    description: Text | None = None
    reference: Text | None = None


ITEM_FIELDS = ("title", "description", "reference")


async def _plan(client, entries, port, operation):
    port, target, _ = await write._context(client, port)
    folders, items = await _tree(client, port)
    known = {f["guid"] for f in folders}
    taken = {str(r["key"]).casefold() for r in [*folders, *items]}
    seen, planned = set(), []
    kind = "folder" if operation == "create_keynote_folders" else "item"
    for index, entry in enumerate(entries):
        label = f"Keynote {kind} {index}"
        if entry.parent_folder_guid is not None and entry.parent_folder_guid not in known:
            raise ValueError(f"{label}: parent folder {entry.parent_folder_guid} does not exist.")
        key = entry.key.casefold()
        if key in taken:
            raise ValueError(f"{label}: key {entry.key!r} already exists in the keynote tree.")
        if key in seen:
            raise ValueError(f"{label}: key {entry.key!r} appears twice.")
        seen.add(key)
        parameters: dict[str, Any] = {"key": entry.key}
        if entry.parent_folder_guid is not None:
            parameters["parentFolderId"] = {"guid": entry.parent_folder_guid}
        fields = ("title",) if kind == "folder" else ITEM_FIELDS
        for name in fields:
            if getattr(entry, name) is not None:
                parameters[name] = getattr(entry, name)
        planned.append(
            {
                "index": index,
                "status": "ready",
                "key": entry.key,
                "parent_folder_guid": entry.parent_folder_guid,
                "parameters": parameters,
            }
        )
    return {"operation": operation, "target": target, "items": planned}


COMMANDS = {
    "create_keynote_folders": (
        "CreateKeynoteFolders",
        "foldersData",
        "keynoteFolderIdsOrErrors",
        "keynoteFolderId",
    ),
    "create_keynote_items": (
        "CreateKeynoteItems",
        "itemsData",
        "keynoteItemIdsOrErrors",
        "keynoteItemId",
    ),
}


async def _dispatch(client, receipt):
    command, key, answer, id_key = COMMANDS[receipt["operation"]]
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    try:
        raw = await client.tapir(
            port, command, {key: [i["parameters"] for i in items]}, timeout=timeout
        )
    except ArchicadError as exc:
        for item in items:
            item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Outcome unknown; inspect Archicad. Never retry this token."
        return
    receipt["raw_response"] = raw
    rows = raw.get(answer)
    if not isinstance(rows, list) or len(rows) != len(items):
        for item in items:
            item.update(status="unknown", error="Unexpected response cardinality.")
        return
    created = []
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        guid = _guid(row.get(id_key)) if isinstance(row, dict) else None
        if guid:
            item.update(status="unverified", guid=guid)
            created.append(item)
        elif isinstance(row, dict) and "error" in row:
            item.update(status="failed", error=row["error"])
        else:
            item.update(status="unknown", error="Missing keynote ID or error; inspect Archicad.")
    if not created:
        return
    try:
        folders, entries = await _tree(client, port, timeout)
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = f"Keynote tree: {exc}"
        return
    by_guid = {
        r["guid"]: r
        for r in (folders if receipt["operation"] == "create_keynote_folders" else entries)
    }
    for item in created:
        row = by_guid.get(item["guid"])
        if row is None:
            item.update(status="verification_failed", mismatches=["missing"])
            continue
        item["after"] = row
        expected = {"key": item["key"], "parent_folder_guid": item["parent_folder_guid"]}
        expected.update({k: v for k, v in item["parameters"].items() if k in ITEM_FIELDS})
        differences = [k for k, v in expected.items() if row.get(k) != v]
        if differences:
            item.update(status="verification_failed", mismatches=differences)
        else:
            item["status"] = "verified"


async def _create(client, entries, model, maximum, port, dry_run, token, operation):
    if not 1 <= len(entries) <= maximum:
        raise ValueError(f"Pass between 1 and {maximum} entries.")
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


async def create_keynote_folders(
    client: ArchicadClient,
    folders: list[dict | KeynoteFolderCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 50 new keynote folders (parent_folder_guid?, key, title)."""
    return await _create(
        client,
        folders,
        KeynoteFolderCreate,
        MAX_FOLDERS,
        port,
        dry_run,
        confirmation_token,
        "create_keynote_folders",
    )


async def create_keynote_items(
    client: ArchicadClient,
    items: list[dict | KeynoteItemCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 100 new keynote items (parent_folder_guid?, key, texts)."""
    return await _create(
        client,
        items,
        KeynoteItemCreate,
        MAX_ITEMS,
        port,
        dry_run,
        confirmation_token,
        "create_keynote_items",
    )
