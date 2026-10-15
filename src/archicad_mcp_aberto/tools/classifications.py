"""Classification systems and element classifications (official JSON API).

list_classifications reads the systems and the item tree of one system. set_classifications
changes which item an element has in a system, with the shared preview, single-use token
and receipts; item None removes the element's classification in that system. Never saves.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Annotated, Any
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import (
    ArchicadClient,
    ArchicadError,
    CommandFailed,
    TapirError,
    resolve_port,
)
from archicad_mcp_aberto.tools import edit, read, write
from archicad_mcp_aberto.tools.issues import _unknown

MAX_CHANGES = 100


def _guid(value: Any) -> str | None:
    try:
        return str(UUID(value)).upper()
    except (ValueError, TypeError, AttributeError):
        return None


async def _systems(client: ArchicadClient, port: int) -> list[dict]:
    rows = (await client.command(port, "GetAllClassificationSystems")).get("classificationSystems")
    if not isinstance(rows, list):
        raise ValueError("Unexpected classification system response.")
    out = []
    for row in rows:
        identifier = row.get("classificationSystemId") if isinstance(row, dict) else None
        guid = _guid(identifier.get("guid")) if isinstance(identifier, dict) else None
        if guid:
            out.append(
                {
                    "guid": guid,
                    **{k: row.get(k) for k in ("name", "version", "description", "source", "date")},
                }
            )
    return out


def _flatten(rows: Any, parent: str | None, depth: int, out: list[dict]) -> list[dict]:
    for row in rows if isinstance(rows, list) else []:
        item = row.get("classificationItem") if isinstance(row, dict) else None
        identifier = item.get("classificationItemId") if isinstance(item, dict) else None
        guid = _guid(identifier.get("guid")) if isinstance(identifier, dict) else None
        if not guid:
            continue
        out.append(
            {
                "guid": guid,
                "id": item.get("id"),
                "name": item.get("name"),
                "description": item.get("description"),
                "parent_guid": parent,
                "depth": depth,
            }
        )
        _flatten(item.get("children"), guid, depth + 1, out)
    return out


async def _items(client: ArchicadClient, port: int, system_guid: str) -> list[dict]:
    result = await client.command(
        port, "GetAllClassificationsInSystem", {"classificationSystemId": {"guid": system_guid}}
    )
    if not isinstance(result.get("classificationItems"), list):
        raise ValueError("Unexpected classification item response.")
    return _flatten(result["classificationItems"], None, 0, [])


def _pick(rows: list[dict], wanted: str, keys: tuple[str, ...], noun: str) -> dict:
    """By GUID, else by the first key that matches exactly (ignoring case); never guesses."""
    guid = _guid(wanted)
    if guid:
        found = [r for r in rows if r["guid"] == guid]
        if found:
            return found[0]
    text = wanted.strip().casefold()
    for key in keys:
        found = [r for r in rows if isinstance(r.get(key), str) and r[key].casefold() == text]
        if len(found) == 1:
            return found[0]
        if found:
            options = ", ".join(f"{r.get('name')!r} ({r['guid']})" for r in found)
            raise ValueError(f"{noun} {wanted!r} is ambiguous: {options}. Pass its GUID.")
    raise ValueError(f"{noun} {wanted!r} does not exist.")


def _pick_system(systems: list[dict], wanted: str) -> dict:
    return _pick(systems, wanted, ("name",), "Classification system")


async def list_classifications(
    client: ArchicadClient,
    system: str | None = None,
    port: int | None = None,
    query: str | None = None,
    offset: int = 0,
    limit: int = 200,
) -> dict[str, Any]:
    read.page_args(offset, limit, 500)
    port = await resolve_port(client, port)
    systems = await _systems(client, port)
    if system is None:
        return {"port": port, "systems": systems}
    chosen = _pick_system(systems, system)
    items = await _items(client, port, chosen["guid"])
    if query:
        text = query.casefold()
        items = [
            i
            for i in items
            if any(isinstance(i[k], str) and text in i[k].casefold() for k in ("id", "name"))
        ]
    return {
        "port": port,
        "system": chosen,
        "total": len(items),
        "offset": offset,
        "items": items[offset : offset + limit],
    }


class ClassificationChange(write.InputModel):
    element_guid: str
    system: str
    item: str | None

    @field_validator("element_guid")
    @classmethod
    def canonical_guid(cls, value: str) -> str:
        return str(UUID(value)).upper()

    @field_validator("system", "item")
    @classmethod
    def not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank; use item null to remove a classification.")
        return value


async def _current(
    client: ArchicadClient,
    port: int,
    pairs: list[tuple[str, str]],
    timeout: float | None = None,
) -> dict[tuple[str, str], dict]:
    """{"item_guid": GUID or None} or {"error": ...} for each (element, system) pair."""
    elements = list(dict.fromkeys(e for e, _ in pairs))
    systems = list(dict.fromkeys(s for _, s in pairs))
    extra = {} if timeout is None else {"timeout": timeout}
    result = await client.command(
        port,
        "GetClassificationsOfElements",
        {
            "elements": read.element_ids(elements),
            "classificationSystemIds": [{"classificationSystemId": {"guid": s}} for s in systems],
        },
        **extra,
    )
    rows = result.get("elementClassifications")
    if not isinstance(rows, list) or len(rows) != len(elements):
        raise ValueError("Unexpected classification response cardinality.")
    out: dict[tuple[str, str], dict] = {}
    for element, row in zip(elements, rows, strict=True):
        entries = row.get("classificationIds") if isinstance(row, dict) else None
        for index, system in enumerate(systems):
            if not isinstance(entries, list) or len(entries) != len(systems):
                error = row.get("error") if isinstance(row, dict) else row
                out[(element, system)] = {"error": error or "Unexpected classification row."}
                continue
            entry = entries[index]
            identifier = entry.get("classificationId") if isinstance(entry, dict) else None
            if not isinstance(identifier, dict):
                error = entry.get("error") if isinstance(entry, dict) else entry
                out[(element, system)] = {"error": error or "Unexpected classification entry."}
                continue
            item = identifier.get("classificationItemId")
            out[(element, system)] = {
                "item_guid": _guid(item.get("guid")) if isinstance(item, dict) else None
            }
    return out


async def _plan(client, changes, port, operation):
    guids = list(dict.fromkeys(c.element_guid for c in changes))
    port, target, rows = await edit._editable(client, guids, port)
    elements = dict(zip(guids, rows, strict=True))
    systems = await _systems(client, port)
    trees: dict[str, dict[str, dict]] = {}
    resolved = []
    for index, change in enumerate(changes):
        label = f"Change {index} ({change.element_guid})"
        try:
            system = _pick_system(systems, change.system)
            if system["guid"] not in trees:
                items = await _items(client, port, system["guid"])
                trees[system["guid"]] = {i["guid"]: i for i in items}
            item = (
                None
                if change.item is None
                else _pick(
                    list(trees[system["guid"]].values()), change.item, ("id", "name"), "Item"
                )
            )
        except ValueError as exc:
            raise ValueError(f"{label}: {exc}") from None
        resolved.append((change, system, item))
    pairs = [(c.element_guid, s["guid"]) for c, s, _ in resolved]
    if len(set(pairs)) != len(pairs):
        raise ValueError("Each element and classification system may appear only once per call.")
    current = await _current(client, port, pairs)
    plan_items = []
    for index, (change, system, item) in enumerate(resolved):
        before = current[(change.element_guid, system["guid"])]
        if "error" in before:
            raise ValueError(
                f"Change {index} ({change.element_guid}): cannot read its classification "
                f"({before['error']})."
            )
        old = trees[system["guid"]].get(before["item_guid"]) if before["item_guid"] else None
        classification: dict[str, Any] = {"classificationSystemId": {"guid": system["guid"]}}
        if item is not None:
            classification["classificationItemId"] = {"guid": item["guid"]}
        row = elements[change.element_guid]
        plan_items.append(
            {
                "index": index,
                "status": "ready",
                "element_guid": change.element_guid,
                "elementType": row.get("type"),
                "floorIndex": row.get("floorIndex"),
                "layerIndex": row.get("layerIndex"),
                "system": {k: system.get(k) for k in ("guid", "name", "version")},
                "before": _summary(old, before["item_guid"]),
                "new": _summary(item, item["guid"] if item else None),
                "unchanged": before["item_guid"] == (item["guid"] if item else None),
                "parameters": {
                    "elementId": {"guid": change.element_guid},
                    "classificationId": classification,
                },
            }
        )
    return {"operation": operation, "target": target, "items": plan_items}


def _summary(item: dict | None, guid: str | None) -> dict | None:
    if guid is None:
        return None
    if item is None:
        return {"guid": guid}
    return {k: item.get(k) for k in ("guid", "id", "name")}


def _wanted(item: dict) -> str | None:
    identifier = item["parameters"]["classificationId"].get("classificationItemId")
    return identifier["guid"] if identifier else None


async def _dispatch(client: ArchicadClient, receipt: dict) -> None:
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    try:
        raw = await client.command(
            port,
            "SetClassificationsOfElements",
            {"elementClassifications": [i["parameters"] for i in items]},
            timeout=timeout,
        )
    except ArchicadError as exc:
        for item in items:
            item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Outcome is unknown. Inspect Archicad; do not retry this plan."
        return
    receipt["raw_response"] = raw
    rows = raw.get("executionResults")
    if not isinstance(rows, list) or len(rows) != len(items):
        for item in items:
            item.update(
                status="unknown", error="Unexpected response cardinality; inspect Archicad."
            )
        return
    written = []
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        if isinstance(row, dict) and row.get("success") is True:
            item["status"] = "unverified"
            written.append(item)
        elif isinstance(row, dict) and row.get("success") is False:
            item.update(status="failed", error=row.get("error"))
        else:
            item.update(status="unknown", error="Unexpected result; inspect Archicad.")
    if not written:
        return
    try:
        after = await _current(
            client,
            port,
            [(i["element_guid"], i["system"]["guid"]) for i in written],
            timeout,
        )
        for item in written:
            row = after[(item["element_guid"], item["system"]["guid"])]
            item["after"] = row
            ok = "error" not in row and row["item_guid"] == _wanted(item)
            item["status"] = "verified" if ok else "verification_failed"
            if not ok:
                item["mismatches"] = ["classificationItemId"]
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)


async def set_classifications(
    client: ArchicadClient,
    changes: list[dict | ClassificationChange],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 100 classifications: element, system and item (None removes).

    System by GUID or name, item by GUID, ID code or name; an ambiguous name is refused.
    The preview shows the current and the new item; applying reads every one back.
    """
    if not 1 <= len(changes) <= MAX_CHANGES:
        raise ValueError(f"Pass between 1 and {MAX_CHANGES} classification changes.")
    validated = [
        c if isinstance(c, ClassificationChange) else ClassificationChange.model_validate(c)
        for c in changes
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "set_classifications",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )


class ClassificationItemCreate(write.InputModel):
    system_guid: str
    parent_guid: str
    id: Annotated[str, Field(min_length=1, max_length=255)]
    name: Annotated[str, Field(min_length=1, max_length=255)]
    description: Annotated[str, Field(max_length=10000)] = ""

    @field_validator("system_guid", "parent_guid")
    @classmethod
    def valid_guid(cls, value):
        guid = UUID(value)
        if not guid.int:
            raise ValueError("System and parent GUIDs must not be null.")
        return str(guid).upper()

    @field_validator("id", "name")
    @classmethod
    def visible(cls, value):
        if not value.strip() or value != value.strip():
            raise ValueError("ID and name must be visible and have no outer whitespace.")
        return value


async def _creation_tree(client, port, system_guid, timeout=None):
    raw = await client.command(
        port,
        "GetAllClassificationsInSystem",
        {"classificationSystemId": {"guid": system_guid}},
        timeout=timeout,
    )
    roots = raw.get("classificationItems")
    if not isinstance(roots, list):
        raise ValueError("Unexpected classification tree.")
    rows, seen = [], set()
    stack = [(r, None, 0) for r in reversed(roots)]
    while stack:
        wrapper, parent, depth = stack.pop()
        row = wrapper.get("classificationItem") if isinstance(wrapper, dict) else None
        identifier = row.get("classificationItemId") if isinstance(row, dict) else None
        guid = _guid(identifier.get("guid")) if isinstance(identifier, dict) else None
        if (
            not guid
            or not UUID(guid).int
            or guid in seen
            or any(not isinstance(row.get(k), str) for k in ("id", "name", "description"))
            or not isinstance(row.get("children", []), list)
        ):
            raise ValueError("Malformed classification item or duplicate GUID.")
        seen.add(guid)
        rows.append(
            {
                "guid": guid,
                "parent_guid": parent,
                "depth": depth,
                **{k: row[k] for k in ("id", "name", "description")},
            }
        )
        stack.extend((child, guid, depth + 1) for child in reversed(row.get("children", [])))
    return rows


async def _creation_plan(client, entries, port, operation):
    port, target, _ = await write._context(client, port)
    systems = await _systems(client, port)
    available = {s["guid"]: s for s in systems}
    trees, items, seen = {}, [], set()
    for index, entry in enumerate(entries):
        if entry.system_guid not in available:
            raise ValueError("Classification system does not exist; pass its GUID.")
        if entry.system_guid not in trees:
            trees[entry.system_guid] = await _creation_tree(client, port, entry.system_guid)
        tree = trees[entry.system_guid]
        parent = next((r for r in tree if r["guid"] == entry.parent_guid), None)
        if parent is None:
            raise ValueError("Parent classification item does not exist in that system.")
        key = (entry.system_guid, entry.id.casefold())
        if key in seen or any(r["id"].casefold() == key[1] for r in tree):
            raise ValueError("Classification ID already exists in this system or batch.")
        seen.add(key)
        items.append(
            {
                "index": index,
                "status": "ready",
                "system": available[entry.system_guid],
                "parent": parent,
                "parameters": {
                    "newClassificationItems": [
                        {
                            "classificationSystemId": {"guid": entry.system_guid},
                            "parentClassificationItemId": {"guid": entry.parent_guid},
                            "classificationItemDetails": {
                                "id": entry.id,
                                "name": entry.name,
                                "description": entry.description,
                            },
                        }
                    ]
                },
            }
        )
    target["classification_trees"] = trees
    return {"operation": operation, "target": target, "items": items}


async def _creation_dispatch(client, receipt):
    port, timeout = receipt["target"]["port"], receipt["write_timeout_seconds"]
    before = deepcopy(receipt["target"]["classification_trees"])
    receipt["undo_scope"] = "Each item is one native command and Undo step."
    for index, item in enumerate(receipt["items"]):
        if not await write._guard_sequential_context(client, receipt, index):
            break
        if index:
            system = item["system"]["guid"]
            try:
                systems = {row["guid"]: row for row in await _systems(client, port)}
                tree = await _creation_tree(client, port, system, timeout)
                unchanged = systems.get(system) == item["system"] and tree == before[system]
            except (ArchicadError, ValueError) as exc:
                unchanged = False
                receipt["inventory_error"] = str(exc)
            if not unchanged:
                error = "Classification tree changed between batch items; run a new preview."
                for later in receipt["items"][index:]:
                    later.update(status="failed", not_attempted=True, error=error)
                break
        try:
            raw = await client.tapir(
                port, "CreateClassificationItems", item["parameters"], timeout=timeout
            )
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
        results = raw.get("executionResults")
        # In this pinned source successful creation appends no execution result.
        # Send ONE entry per native call so a returned error belongs to this item.
        if isinstance(results, list) and len(results) == 1 and isinstance(results[0], dict):
            row = results[0]
            if row.get("success") is False and isinstance(row.get("error"), dict):
                item.update(status="failed", error=row["error"])
                continue
        if results != []:
            _unknown(receipt, index, "Unexpected native classification creation response.")
            break
        item["status"] = "unverified"
        system = item["system"]["guid"]
        previous = {r["guid"]: r for r in before[system]}
        try:
            rows = await _creation_tree(client, port, system, timeout)
        except (ArchicadError, ValueError) as exc:
            receipt["verification_error"] = str(exc)
            for later in receipt["items"][index + 1 :]:
                later.update(
                    status="failed", not_attempted=True, error="Classification read-back failed."
                )
            break
        current = {r["guid"]: r for r in rows}
        added = [r for g, r in current.items() if g not in previous]
        expected = item["parameters"]["newClassificationItems"][0]["classificationItemDetails"]
        matches = len(added) == 1 and all(added[0][k] == v for k, v in expected.items())
        matches = matches and added[0]["parent_guid"] == item["parent"]["guid"]
        unchanged = all(current.get(g) == r for g, r in previous.items())
        item["after"] = added
        ok = matches and unchanged
        item["status"] = "verified" if ok else "verification_failed"
        if ok:
            item["classification_item_guid"] = added[0]["guid"]
        else:
            item["mismatches"] = ["new_item_or_existing_tree"]
            for later in receipt["items"][index + 1 :]:
                later.update(
                    status="failed",
                    not_attempted=True,
                    error=(
                        "Stopped after a classification verification mismatch; run a new preview."
                    ),
                )
            break
        before[system] = rows


async def create_classification_items(
    client: ArchicadClient,
    items: list[dict | ClassificationItemCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/create 1–50 items under existing system and parent GUIDs.

    ID/name/description only, no recursive children or new systems. Shared token,
    explicit apply port and durable receipts; independently reads back new GUID,
    ID/name/description/parent and preserved prior tree. Never deletes or saves.
    """
    if not 1 <= len(items) <= 50:
        raise ValueError("Pass between 1 and 50 classification items.")
    entries = [
        i if isinstance(i, ClassificationItemCreate) else ClassificationItemCreate.model_validate(i)
        for i in items
    ]
    return await write._write(
        client,
        entries,
        port,
        dry_run,
        confirmation_token,
        "create_classification_items",
        planner_override=_creation_plan,
        dispatcher_override=_creation_dispatch,
    )
