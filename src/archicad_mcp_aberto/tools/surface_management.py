"""GUID-based surface tasks with verified checkpoints and conservative usage reports."""

from __future__ import annotations

import asyncio
import time
from copy import deepcopy
from dataclasses import dataclass, field
from uuid import UUID, uuid4
from weakref import WeakKeyDictionary

from pydantic import field_validator

from archicad_mcp_aberto.connection import ArchicadError, resolve_port
from archicad_mcp_aberto.tools import (
    attributes_details,
    drafting,
    model_tasks,
    project_save,
    surfaces,
    write,
)


@dataclass
class State:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    previews: dict = field(default_factory=dict)


_states: WeakKeyDictionary = WeakKeyDictionary()


class SurfaceRequest(write.InputModel):
    guid: str
    new_name: str | None = None

    @field_validator("guid")
    @classmethod
    def valid_guid(cls, value):
        return guid(value)


def guid(value):
    parsed = UUID(value)
    if not parsed.int:
        raise ValueError("Null GUIDs are refused.")
    return str(parsed).upper()


def folder_tree(node, parent=None):
    """Keep official folder GUIDs and membership, including the root."""
    key = guid(node["attributeFolderId"]["guid"])
    result = {
        key: {
            "name": node["name"],
            "parent": parent,
            "attributes": [guid(row["attributeId"]["guid"]) for row in node.get("attributes", [])],
        }
    }
    for child in node.get("subfolders", []):
        result.update(folder_tree(child["attributeFolder"], key))
    return result


async def folders(client, port):
    raw = await client.command(port, "GetAttributeFolderStructure", {"attributeType": "Surface"})
    return folder_tree(raw["attributeFolder"])


async def details(client, port, ids):
    rows = await surfaces._details(client, port, ids)
    official = await client.command(
        port,
        "GetSurfaceAttributes",
        {"attributeIds": [{"attributeId": {"guid": key}} for key in ids]},
    )
    official_rows = official.get("attributes", [])
    if len(official_rows) != len(ids):
        raise ValueError("Incomplete official surface settings readback.")
    result = {}
    for key, row, full in zip(ids, rows, official_rows, strict=True):
        if "error" in row or guid(row["attributeId"]["guid"]) != key:
            raise ValueError(f"Cannot verify surface {key}.")
        if "surfaceAttribute" not in full or "error" in full:
            raise ValueError(f"Cannot read full official surface {key}.")
        row = {**row, "official": full["surfaceAttribute"]}
        if row["official"].get("name") != row["name"]:
            raise ValueError("Official and Tapir surface identities disagree.")
        result[key] = row
    return result


def configuration(row):
    result = {key: value for key, value in row.items() if key != "name"}
    if "official" in result:
        result["official"] = {
            key: value for key, value in result["official"].items() if key != "name"
        }
    return result


async def plan(client, operation, requests, target_folder, port):
    port = await resolve_port(client, port)
    context = await model_tasks._settled_context(client, port)
    if operation not in {"rename", "move"}:
        raise ValueError("Operation must be rename or move.")
    if not 1 <= len(requests) <= 50:
        raise ValueError("Provide 1–50 surface requests.")
    requests = [
        SurfaceRequest.model_validate(row).model_dump(exclude_none=True) for row in requests
    ]
    ids = [guid(row["guid"]) for row in requests]
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate surface GUIDs.")
    before = await details(client, port, ids)
    tree = await folders(client, port)
    destination = guid(target_folder) if target_folder else None
    if operation == "move" and destination not in tree:
        raise ValueError("Destination must be an existing Surface folder GUID.")
    if operation == "rename":
        available = await client.command(
            port,
            "IsAddOnCommandAvailable",
            {
                "addOnCommandId": {
                    "commandNamespace": "ArchicadMcpAberto",
                    "commandName": "RenameAttributes",
                }
            },
        )
        if available.get("isAvailable", available.get("available")) is not True:
            raise ValueError("Native RenameAttributes is required before preparing a rename.")
    occupied = {
        row["name"].casefold(): guid(row["attributeId"]["guid"])
        for row in await drafting._attributes(client, port, "Surface")
    }
    items = []
    for index, (key, request) in enumerate(zip(ids, requests, strict=True)):
        item = {"index": index, "guid": key, "status": "ready", "before": before[key]}
        if operation == "rename":
            name = request.get("new_name", "")
            if (
                not isinstance(name, str)
                or not name.strip()
                or name != name.strip()
                or "\x00" in name
                or len(name.encode("utf-16-le")) // 2 > 255
            ):
                raise ValueError("Names must be visible, trimmed and at most 255 UTF-16 units.")
            if occupied.get(name.casefold(), key) != key:
                raise ValueError(f"Surface name {name!r} is occupied.")
            occupied[name.casefold()] = key
            item["new_name"] = name
        else:
            item["target_folder_guid"] = destination
        items.append(item)
    return {
        "operation": operation,
        "target": {"port": port, "project": context},
        "items": items,
        "folders": tree,
        "file": project_save._fingerprint(project_save._path(context["projectPath"])),
    }


async def manage_surfaces(
    client,
    operation,
    requests,
    target_folder_guid=None,
    port=None,
    dry_run=True,
    confirmation_token=None,
):
    """Preview/apply exact GUID operations. Checkpoint and save the same PLN."""
    if client.session_id is None:
        raise RuntimeError("Client must be entered.")
    state = _states.setdefault(client, State())
    async with state.lock:
        current = await plan(client, operation, requests, target_folder_guid, port)
        now = time.monotonic()
        state.previews = {key: value for key, value in state.previews.items() if value[0] > now}
        if dry_run:
            token = str(uuid4())
            if len(state.previews) >= 16:
                raise ValueError("Too many pending previews.")
            state.previews[token] = (now + write.PREVIEW_SECONDS, deepcopy(current))
            return {**current, "dry_run": True, "confirmation_token": token}
        if port is None:
            raise ValueError("Explicit port required.")
        previous = state.previews.pop(confirmation_token, None)
        if previous is None or previous[1] != current:
            raise ValueError("Expired, consumed or changed preview. Prepare again.")
        receipt = {**current, "receipt_id": str(uuid4()), "status": "prepared"}
        receipt["prepared_receipt_path"] = write._journal(receipt, "prepared")
        checkpoint_preview = await model_tasks.begin_model_task(client, port)
        checkpoint = await model_tasks.begin_model_task(
            client, port, False, checkpoint_preview["confirmation_token"]
        )
        receipt["checkpoint"] = checkpoint
        if checkpoint["status"] != "verified":
            raise ValueError("Backup failed. No attribute write dispatched.")
        refreshed = await plan(client, operation, requests, target_folder_guid, port)
        if (
            refreshed["items"] != current["items"]
            or refreshed["folders"] != current["folders"]
            or model_tasks._identity(refreshed["target"]["project"])
            != model_tasks._identity(current["target"]["project"])
        ):
            raise ValueError("Surfaces/folders/project changed during checkpoint.")
        for item in receipt["items"]:
            try:
                if await project_save._context(client, port) != refreshed["target"]["project"]:
                    raise ValueError("Project changed before dispatch.")
                item["status"] = "dispatching"
                write._journal(receipt, f"item-{item['index']}-prepared")
                if operation == "rename":
                    response = await client.own_addon(
                        port,
                        "RenameAttributes",
                        {
                            "attributeType": "Surface",
                            "renames": [{"guid": item["guid"], "newName": item["new_name"]}],
                        },
                        timeout=write.write_timeout(),
                    )
                    result = response["results"][0]
                    if guid(result["guid"]) != item["guid"] or result.get("success") is not True:
                        item.update(status="failed", error=result)
                        break
                else:
                    response = await client.command(
                        port,
                        "MoveAttributesAndFolders",
                        {
                            "attributeFolderIds": [],
                            "attributeIds": [{"attributeId": {"guid": item["guid"]}}],
                            "targetFolderId": {"guid": item["target_folder_guid"]},
                        },
                        timeout=write.write_timeout(),
                    )
                item["response"] = response
                after = (await details(client, port, [item["guid"]]))[item["guid"]]
                item["after"] = after
                expected_name = item.get("new_name", item["before"]["name"])
                valid = after["name"] == expected_name and configuration(after) == configuration(
                    item["before"]
                )
                if operation == "move":
                    valid = (
                        valid
                        and item["guid"]
                        in (await folders(client, port))[item["target_folder_guid"]]["attributes"]
                    )
                item["status"] = "verified" if valid else "verification_failed"
                write._journal(receipt, f"item-{item['index']}-result")
                if not valid:
                    break
                refreshed["target"]["project"] = await model_tasks._settled_context(client, port)
                if model_tasks._identity(refreshed["target"]["project"]) != model_tasks._identity(
                    current["target"]["project"]
                ):
                    raise ValueError("Project identity changed.")
            except (ArchicadError, ValueError, KeyError, TypeError) as exc:
                item.update(
                    status="unknown" if item["status"] == "dispatching" else "failed",
                    error=str(exc),
                )
                break
        receipt["status"] = "needs_review"
        if all(item["status"] == "verified" for item in receipt["items"]):
            save_preview = await model_tasks.finish_model_task(
                client, checkpoint["task_token"], port
            )
            try:
                receipt["save"] = await model_tasks.finish_model_task(
                    client,
                    checkpoint["task_token"],
                    port,
                    False,
                    save_preview["confirmation_token"],
                )
                receipt["status"] = receipt["save"]["status"]
            except (ArchicadError, ValueError, OSError) as exc:
                receipt["save_error"] = str(exc)
                receipt["status"] = "needs_review"
        receipt["receipt_path"] = write._journal(receipt, "result")
        return receipt


def references(value, surfaces_by_guid, surfaces_by_index, path=""):
    """Report explicit surface fields and exact GUID references without guessing indices."""
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            location = f"{path}.{key}"
            if key == "guid" and isinstance(child, str) and child.upper() in surfaces_by_guid:
                found.append((child.upper(), location))
            elif (
                (
                    "surface" in key.casefold()
                    or key.casefold() in {"material", "materialindex", "materialind", "cutmaterial"}
                )
                and type(child) is int
                and child in surfaces_by_index
            ):
                found.append((surfaces_by_index[child], location))
            found.extend(references(child, surfaces_by_guid, surfaces_by_index, location))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(references(child, surfaces_by_guid, surfaces_by_index, f"{path}[{index}]"))
    return found


async def audit_surface_usage(client, port=None):
    port = await resolve_port(client, port)
    headers = await drafting._attributes(client, port, "Surface")
    ids = [guid(row["attributeId"]["guid"]) for row in headers]
    by_guid = {}
    for offset in range(0, len(ids), 100):
        by_guid.update(await details(client, port, ids[offset : offset + 100]))
    by_index = {row["index"]: key for key, row in by_guid.items() if "index" in row}
    usage = {key: [] for key in by_guid}
    coverage, failures = [], []

    async def collect(label, call):
        try:
            data = await call
            errors = collect_errors(data)
            if errors:
                failures.append({"source": label, "errors": errors})
            for key, location in references(data, by_guid, by_index):
                usage[key].append({"source": label, "path": location})
            coverage.append(label)
            return data
        except (ArchicadError, ValueError, KeyError, TypeError) as exc:
            failures.append({"source": label, "error": str(exc)})
            return {}

    for kind in ("composites", "profiles"):
        await collect(kind, attributes_details.get_attribute_details(client, kind, port=port))
    materials = await drafting._attributes(client, port, "BuildingMaterial")
    for offset in range(0, len(materials), 100):
        await collect(
            "building_material_surface",
            client.tapir(
                port,
                "GetBuildingMaterials",
                {
                    "attributeIds": [
                        {"attributeId": row["attributeId"]}
                        for row in materials[offset : offset + 100]
                    ]
                },
            ),
        )
    raw = await client.command(port, "GetAllElements")
    elements = raw["elements"]
    seen = set()
    while elements:
        batch, elements = elements[:100], elements[100:]
        batch = [row for row in batch if guid(row["elementId"]["guid"]) not in seen]
        if not batch:
            continue
        seen.update(guid(row["elementId"]["guid"]) for row in batch)
        await collect(
            "element_face_overrides",
            client.tapir(
                port, "GetDetailsOfElements", {"elements": batch, "fields": ["type", "details"]}
            ),
        )
        children = await collect(
            "hierarchical_subelements",
            client.tapir(port, "GetSubelementsOfHierarchicalElements", {"elements": batch}),
        )
        elements.extend(
            {"elementId": {"guid": key}} for key in element_references(children) if key not in seen
        )
    limitations = [
        "No exhaustive SDK reference graph or certified unused-surface predicate "
        "is available in this adapter.",
        "GDL scripts/macros, dynamically generated materials, library defaults and "
        "favorites are not exhaustively evaluated.",
        "Profile vector-image edge overrides and all hierarchical component memo "
        "fields are not exhaustively decoded.",
        "Other databases, hotlinks, design options, rendering-engine data and "
        "external references are not exhaustively verified.",
        "Composite/profile building-material dependencies are queried but their "
        "complete transitive graph is not certified.",
        "Unsupported or omitted API fields and per-item errors prevent proof of non-use.",
    ]
    return {
        "port": port,
        "coverage": coverage,
        "failures": failures,
        "scanned_elements": len(seen),
        "limitations": limitations,
        "items": [
            {
                "guid": key,
                "name": row["name"],
                "references": usage[key],
                "status": "use_found" if usage[key] else "no_use_found",
                "proven_unused": False,
                "deletion_allowed": False,
            }
            for key, row in by_guid.items()
        ],
    }


def collect_errors(value):
    if isinstance(value, dict):
        return ([value["error"]] if "error" in value else []) + [
            error for child in value.values() for error in collect_errors(child)
        ]
    if isinstance(value, list):
        return [error for child in value for error in collect_errors(child)]
    return []


def element_references(value):
    found = set()
    if isinstance(value, dict):
        element = value.get("elementId")
        if isinstance(element, dict) and "guid" in element:
            found.add(guid(element["guid"]))
        for child in value.values():
            found.update(element_references(child))
    elif isinstance(value, list):
        for child in value:
            found.update(element_references(child))
    return found


async def delete_unused_surfaces(client, surface_guids, port=None):
    """Return candidates and proof limitations. No delete command is dispatched."""
    wanted = {guid(value) for value in surface_guids}
    if not 1 <= len(wanted) <= 50:
        raise ValueError("Provide 1–50 candidate surface GUIDs.")
    audit = await audit_surface_usage(client, port)
    known = {row["guid"] for row in audit["items"]}
    return {
        **audit,
        "items": [row for row in audit["items"] if row["guid"] in wanted]
        + [
            {"guid": key, "status": "not_found", "deletion_allowed": False}
            for key in sorted(wanted - known)
        ],
        "deleted": 0,
        "status": "blocked_unproven_nonuse",
    }
