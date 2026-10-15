"""Flattened Navigator read access through Tapir 1.7.0 GetNavigatorItemTree."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import (
    ArchicadClient,
    ArchicadError,
    CommandFailed,
    TapirError,
    resolve_port,
)
from archicad_mcp_aberto.tools import read, write
from archicad_mcp_aberto.tools.issues import _unknown

NavigatorMap = Literal["ProjectMap", "PublicViewMap", "LayoutBook", "PublisherSets"]
MAPS = ("ProjectMap", "PublicViewMap", "LayoutBook", "PublisherSets")


def _flatten(root: object) -> list[dict]:
    """Preorder traversal preserving native order, with no recursive Python calls."""
    out = []
    stack = [(root, None, 0)]
    while stack:
        node, parent, depth = stack.pop()
        if not isinstance(node, dict):
            raise ValueError("Unexpected navigator node.")
        identifier = node.get("navigatorItemId")
        try:
            guid = str(UUID(identifier["guid"])).upper()
        except (KeyError, TypeError, ValueError, AttributeError):
            raise ValueError("Unexpected navigator item ID.") from None
        if not isinstance(node.get("name"), str) or not isinstance(node.get("type"), str):
            raise ValueError("Unexpected navigator name or type.")
        out.append(
            {
                "guid": guid,
                "name": node["name"],
                "type": node["type"],
                "parent_guid": parent,
                "depth": depth,
                "prefix": node.get("prefix"),
                "uiId": node.get("uiId"),
            }
        )
        # Preserve the identity behind a view and its native inheritance flags.
        # Identical displayed names/IDs alone cannot prove the intended source.
        if "sourceNavigatorItemId" in node:
            try:
                source_guid = UUID(node["sourceNavigatorItemId"]["guid"])
                if not source_guid.int:
                    raise ValueError("Null source GUID.")
            except (KeyError, TypeError, ValueError, AttributeError):
                raise ValueError("Unexpected Navigator source ID.") from None
            out[-1]["source_guid"] = str(source_guid).upper()
        for native, key in (
            ("customName", "custom_name"),
            ("customUiId", "custom_ui_id"),
            ("isIndependent", "is_independent"),
        ):
            if native in node:
                if type(node[native]) is not bool:
                    raise ValueError(f"Unexpected Navigator {native} flag.")
                out[-1][key] = node[native]
        children = node.get("children", [])
        if not isinstance(children, list):
            raise ValueError("Unexpected navigator children.")
        for wrapper in reversed(children):
            if not isinstance(wrapper, dict) or "navigatorItem" not in wrapper:
                raise ValueError("Unexpected navigator child wrapper.")
            stack.append((wrapper["navigatorItem"], guid, depth + 1))
    return out


async def get_navigator_tree(
    client: ArchicadClient,
    navigator_map: NavigatorMap = "ProjectMap",
    port: int | None = None,
    query: str | None = None,
    offset: int = 0,
    limit: int = 200,
    publisher_set_name: str | None = None,
) -> dict:
    """Read a flattened Navigator map, root included at depth 0; never writes.

    Maps: ProjectMap, PublicViewMap, LayoutBook, PublisherSets. Query matches name,
    type or displayed uiId (case-insensitive), before pagination. Parent/depth remain
    relative to the unfiltered tree. PublisherSets returns one set: the exact named
    publisher_set_name, or the first native set when omitted (not all publisher sets).
    """
    if navigator_map not in MAPS:
        raise ValueError(f"navigator_map must be one of {', '.join(MAPS)}.")
    if type(offset) is not int or type(limit) is not int:
        raise ValueError("offset and limit must be integers.")
    read.page_args(offset, limit, 500)
    if publisher_set_name is not None:
        if navigator_map != "PublisherSets":
            raise ValueError("publisher_set_name is only accepted for PublisherSets.")
        if not isinstance(publisher_set_name, str) or not publisher_set_name.strip():
            raise ValueError("publisher_set_name must not be blank.")
    port = await resolve_port(client, port)
    parameters = {"navigatorMapId": navigator_map}
    if publisher_set_name is not None:
        parameters["publisherSetName"] = publisher_set_name
    response = await client.tapir(port, "GetNavigatorItemTree", parameters)
    rows = _flatten(response.get("navigatorItemTree"))
    if query:
        text = query.casefold()
        rows = [
            r
            for r in rows
            if any(
                isinstance(r[k], str) and text in r[k].casefold() for k in ("name", "type", "uiId")
            )
        ]
    result = {
        "port": port,
        "navigator_map": navigator_map,
        "total": len(rows),
        "offset": offset,
        "limit": limit,
        "items": rows[offset : offset + limit],
    }
    if navigator_map == "PublisherSets":
        result["publisher_set_name"] = publisher_set_name
        if publisher_set_name is None:
            result["note"] = (
                "Tapir returns the first publisher set only; "
                "pass publisher_set_name for another set."
            )
    return result


class ViewMapFolder(write.InputModel):
    parent_guid: str
    name: Annotated[str, Field(min_length=1, max_length=255)]

    @field_validator("parent_guid")
    @classmethod
    def valid_guid(cls, value):
        guid = UUID(value)
        if not guid.int:
            raise ValueError("Parent GUID must not be null.")
        return str(guid).upper()

    @field_validator("name")
    @classmethod
    def visible_name(cls, value):
        if not value.strip() or value != value.strip():
            raise ValueError("Folder name must be visible and have no outer whitespace.")
        # CreateViewMapFolder copies this to API_NavigatorItem.uName (UTF-16).
        if "\x00" in value or len(value.encode("utf-16-le")) // 2 > 255:
            raise ValueError("Folder name must fit 255 UTF-16 units and contain no NUL.")
        return value


class ViewMapClone(write.InputModel):
    parent_guid: str
    source_guid: str

    @field_validator("parent_guid", "source_guid")
    @classmethod
    def valid_guid(cls, value):
        return ViewMapFolder.valid_guid(value)


async def _view_tree(client, port, map_id, timeout=None):
    response = await client.tapir(
        port, "GetNavigatorItemTree", {"navigatorMapId": map_id}, timeout=timeout
    )
    rows = _flatten(response.get("navigatorItemTree"))
    if len({r["guid"] for r in rows}) != len(rows) or any(not UUID(r["guid"]).int for r in rows):
        raise ValueError("Duplicate or null Navigator GUID.")
    return rows


async def _view_plan(client, entries, port, operation):
    port, target, _ = await write._context(client, port)
    tree = await _view_tree(client, port, "PublicViewMap")
    target["view_map"] = tree
    folders = operation == "create_view_map_folders"
    source_rows = [] if folders else await _view_tree(client, port, "ProjectMap")
    if not folders:
        target["project_map"] = source_rows
    parents = {r["guid"]: r for r in tree if r["depth"] == 0 or r["type"] == "FolderItem"}
    containers = {r["parent_guid"] for r in source_rows}
    sources = {
        r["guid"]: r
        for r in source_rows
        if r["depth"] > 0 and r["type"] != "FolderItem" and r["guid"] not in containers
    }
    items, seen = [], set()
    for index, entry in enumerate(entries):
        if entry.parent_guid not in parents:
            raise ValueError("Parent must be an existing PublicViewMap root or folder GUID.")
        if folders:
            name, item_type = entry.name, "FolderItem"
            parameters = {"folderName": name, "parentNavigatorItemId": {"guid": entry.parent_guid}}
        else:
            source = sources.get(entry.source_guid)
            if source is None:
                raise ValueError("Source must be an existing ProjectMap viewpoint GUID.")
            name, item_type = source["name"], source["type"]
            parameters = {
                "viewsData": [
                    {
                        "navigatorItemId": {"guid": entry.source_guid},
                        "parentNavigatorItemId": {"guid": entry.parent_guid},
                    }
                ]
            }
        key = (entry.parent_guid, item_type, name.casefold())
        if key in seen or any(
            (r["parent_guid"], r["type"], r["name"].casefold()) == key for r in tree
        ):
            raise ValueError("An item with this name and type already exists under that parent.")
        seen.add(key)
        item = {
            "index": index,
            "status": "ready",
            "name": name,
            "type": item_type,
            "parent_guid": entry.parent_guid,
            "parameters": parameters,
        }
        if not folders:
            item["source"] = source
        items.append(item)
    return {
        "operation": operation,
        "target": target,
        "items": items,
        "undo_note": "No guaranteed Navigator Undo. Remove unwanted new items manually.",
    }


async def _view_dispatch(client, receipt):
    port, timeout = receipt["target"]["port"], receipt["write_timeout_seconds"]
    command = (
        "CreateViewMapFolder"
        if receipt["operation"] == "create_view_map_folders"
        else "CloneProjectMapItemToViewMap"
    )
    before = {r["guid"]: r for r in receipt["target"]["view_map"]}
    receipt["revert_note"] = "No guaranteed Navigator Undo. Remove unwanted new items manually."
    for index, item in enumerate(receipt["items"]):
        if not await write._guard_sequential_context(client, receipt, index):
            break
        try:
            raw = await client.tapir(port, command, item["parameters"], timeout=timeout)
        except (TapirError, CommandFailed) as exc:
            if isinstance(exc.detail, dict) and {"code", "message"} <= exc.detail.keys():
                item.update(status="failed", error=exc.detail)
                continue
            _unknown(receipt, index, exc)
            break
        except ArchicadError as exc:
            _unknown(receipt, index, exc)
            break
        item["write_response"] = raw
        row = raw
        if command == "CloneProjectMapItemToViewMap":
            results = raw.get("navigatorItems")
            row = results[0] if isinstance(results, list) and len(results) == 1 else None
        if isinstance(row, dict) and isinstance(row.get("error"), dict):
            item.update(status="failed", error=row["error"])
            continue
        try:
            guid = str(UUID(row["navigatorItemId"]["guid"])).upper()
            if not UUID(guid).int or guid in before:
                raise ValueError("Null or previously existing Navigator GUID.")
        except (TypeError, KeyError, ValueError, AttributeError) as exc:
            _unknown(receipt, index, f"Invalid created Navigator GUID: {exc}")
            break
        item.update(status="unverified", navigator_guid=guid)
        try:
            rows = await _view_tree(client, port, "PublicViewMap", timeout)
            current = {r["guid"]: r for r in rows}
            after = current.get(guid)
            item["after"] = after
            differences = []
            if after is None:
                differences.append("missing")
            else:
                for key in ("name", "type", "parent_guid"):
                    if after[key] != item[key]:
                        differences.append(key)
                if "source" in item and after["uiId"] != item["source"]["uiId"]:
                    differences.append("uiId")
                if "source" in item and after.get("source_guid") != item["source"]["guid"]:
                    differences.append("source_guid")
            if any(current.get(g) != r for g, r in before.items()):
                differences.append("existing_items_changed")
            if set(current) - set(before) != {guid}:
                differences.append("unexpected_new_items")
            if "project_map" in receipt["target"]:
                if (
                    await _view_tree(client, port, "ProjectMap", timeout)
                    != receipt["target"]["project_map"]
                ):
                    differences.append("project_map_changed")
        except (ArchicadError, ValueError) as exc:
            receipt["verification_error"] = str(exc)
            for later in receipt["items"][index + 1 :]:
                later.update(
                    status="failed", not_attempted=True, error="Navigator read-back failed."
                )
            break
        item["status"] = "verification_failed" if differences else "verified"
        if differences:
            item["mismatches"] = differences
            for later in receipt["items"][index + 1 :]:
                later.update(
                    status="failed",
                    not_attempted=True,
                    error="Stopped after a Navigator verification mismatch; run a new preview.",
                )
            break
        before = current


async def _create_view_items(client, entries, model, port, dry_run, token, operation):
    if not 1 <= len(entries) <= 20:
        raise ValueError("Pass between 1 and 20 items.")
    entries = [e if isinstance(e, model) else model.model_validate(e) for e in entries]
    return await write._write(
        client,
        entries,
        port,
        dry_run,
        token,
        operation,
        planner_override=_view_plan,
        dispatcher_override=_view_dispatch,
    )


async def create_view_map_folders(
    client: ArchicadClient,
    folders: list[dict | ViewMapFolder],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/create 1–20 folders under explicit existing PublicViewMap parent GUIDs.

    One-use token, per-item receipts and tree read-back; no guaranteed Undo. Never saves.
    """
    return await _create_view_items(
        client, folders, ViewMapFolder, port, dry_run, confirmation_token, "create_view_map_folders"
    )


async def clone_to_view_map(
    client: ArchicadClient,
    views: list[dict | ViewMapClone],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/clone 1–20 ProjectMap viewpoints under existing PublicViewMap parent GUIDs.

    Clone inherits native view settings; no custom name/settings or guaranteed Undo.
    Explicit port, one-use token, per-item receipts and tree read-back. Never saves/publishes.
    """
    return await _create_view_items(
        client, views, ViewMapClone, port, dry_run, confirmation_token, "clone_to_view_map"
    )
