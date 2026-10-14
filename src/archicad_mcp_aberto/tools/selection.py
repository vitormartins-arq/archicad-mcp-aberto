"""Selection, highlight and groups (Tapir 1.7.0).

select_elements and highlight_elements change only what the user sees, never the model,
so they act at once and report what Archicad ended with. create_groups changes the model
and uses the shared preview, single-use token and receipts, and reads each group back.
Never saves.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError, resolve_port
from archicad_mcp_aberto.tools import edit, read, write

MAX_GROUPS = 20
Channel = Annotated[int, Field(ge=0, le=255)]


def _canonical(guids: list[str]) -> list[str]:
    out = [str(UUID(g)).upper() for g in guids]
    if len(set(out)) != len(out):
        raise ValueError("Each element may appear only once per call.")
    return out


async def _selected(client, port) -> list[str]:
    response = await client.command(port, "GetSelectedElements")
    rows = response.get("elements")
    if not isinstance(rows, list):
        raise ValueError("Unexpected selection response.")
    return [str(UUID(r["elementId"]["guid"])).upper() for r in rows]


def _results(rows: Any, guids: list[str]) -> list[dict]:
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected selection result cardinality.")
    return [
        {"element_guid": g, "ok": isinstance(r, dict) and r.get("success") is True, "result": r}
        for g, r in zip(guids, rows, strict=True)
    ]


async def select_elements(
    client: ArchicadClient,
    element_guids: list[str],
    port: int | None = None,
    mode: Literal["replace", "add", "remove"] = "replace",
) -> dict:
    """Change the selection: replace it, add to it or remove from it. Model unchanged."""
    if mode == "replace" and not element_guids:
        guids: list[str] = []
    else:
        guids = _canonical(element_guids)
        read.element_ids(guids)  # 1 to 100 GUIDs
    port = await resolve_port(client, port)
    before = await _selected(client, port)
    add = guids if mode in ("replace", "add") else []
    remove = [g for g in before if g not in guids] if mode == "replace" else []
    if mode == "remove":
        remove = guids
    params: dict[str, Any] = {}
    if add:
        params["addElementsToSelection"] = [{"elementId": {"guid": g}} for g in add]
    if remove:
        params["removeElementsFromSelection"] = [{"elementId": {"guid": g}} for g in remove]
    response = await client.tapir(port, "ChangeSelectionOfElements", params) if params else {}
    added = _results(response.get("executionResultsOfAddToSelection", []), add)
    removed = _results(response.get("executionResultsOfRemoveFromSelection", []), remove)
    after = await _selected(client, port)
    wanted = set(after)
    missing = [g for g in add if g not in wanted]
    stayed = [g for g in remove if g in wanted]
    return {
        "port": port,
        "mode": mode,
        "status": "verified" if not missing and not stayed else "verification_failed",
        "selected_count": len(after),
        "not_selected": missing,
        "still_selected": stayed,
        "added": added,
        "removed": removed,
    }


async def highlight_elements(
    client: ArchicadClient,
    element_guids: list[str],
    port: int | None = None,
    color: Annotated[list[Channel], Field(min_length=3, max_length=4)] | None = None,
    wireframe_3d: bool | None = None,
) -> dict:
    """Highlight elements in one RGB(A) color (0-255); an empty list clears the highlight."""
    color = [255, 0, 0, 255] if color is None else list(color)
    if not 3 <= len(color) <= 4 or not all(isinstance(c, int) and 0 <= c <= 255 for c in color):
        raise ValueError("color is [r, g, b] or [r, g, b, a], each 0 to 255.")
    rgba = color + [255] if len(color) == 3 else color
    guids = _canonical(element_guids) if element_guids else []
    elements = read.element_ids(guids) if guids else []
    port = await resolve_port(client, port)
    params: dict[str, Any] = {"elements": elements, "highlightedColors": [rgba] * len(guids)}
    if wireframe_3d is not None:
        params["wireframe3D"] = wireframe_3d
    response = await client.tapir(port, "HighlightElements", params)
    ok = response.get("success") is True
    return {
        "port": port,
        "status": "done" if ok else "failed",
        "highlighted": len(guids) if ok else 0,
        "cleared": not guids and ok,
        "color": rgba,
        "result": response,
    }


async def _groups_of(client, port, guids, timeout=None) -> dict[str, str | None]:
    extra = {} if timeout is None else {"timeout": timeout}
    response = await client.tapir(
        port, "GetGroupsOfElements", {"elements": read.element_ids(guids)}, **extra
    )
    rows = response.get("groupGuids")
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected group response cardinality.")
    out: dict[str, str | None] = {}
    for guid, row in zip(guids, rows, strict=True):
        group = row.get("groupId") if isinstance(row, dict) else None
        found = group.get("guid") if isinstance(group, dict) else None
        # Tapir answers an element outside every group with an error item.
        out[guid] = str(UUID(found)).upper() if isinstance(found, str) else None
    return out


async def _members(client, port, groups, timeout=None) -> list[Any]:
    extra = {} if timeout is None else {"timeout": timeout}
    response = await client.tapir(
        port,
        "GetElementsOfGroups",
        {"groups": [{"groupId": {"guid": g}} for g in groups]},
        **extra,
    )
    rows = response.get("elementsOfGroups")
    if not isinstance(rows, list) or len(rows) != len(groups):
        raise ValueError("Unexpected group members response cardinality.")
    return rows


def _guids_of(row: Any) -> list[str] | None:
    elements = row.get("elements") if isinstance(row, dict) else None
    if not isinstance(elements, list):
        return None
    return [str(UUID(e["elementId"]["guid"])).upper() for e in elements]


async def get_element_groups(
    client: ArchicadClient, element_guids: list[str], port: int | None = None
) -> dict:
    """For up to 100 elements: the group that directly holds each one and its members."""
    guids = _canonical(element_guids)
    read.element_ids(guids)
    port = await resolve_port(client, port)
    groups = await _groups_of(client, port, guids)
    distinct = list(dict.fromkeys(g for g in groups.values() if g))
    members = dict(zip(distinct, await _members(client, port, distinct), strict=True))
    return {
        "port": port,
        "elements": [{"element_guid": g, "group_guid": groups[g]} for g in guids],
        "groups": [{"group_guid": g, "element_guids": _guids_of(members[g])} for g in distinct],
    }


class GroupCreate(write.InputModel):
    element_guids: Annotated[list[str], Field(min_length=2, max_length=100)]

    @field_validator("element_guids")
    @classmethod
    def canonical(cls, value: list[str]) -> list[str]:
        return _canonical(value)


async def _plan(client, groups, port, operation):
    guids = [g for group in groups for g in group.element_guids]
    if len(set(guids)) != len(guids):
        raise ValueError("An element may belong to only one new group per call.")
    if len(guids) > read.MAX_ELEMENTS_PER_CALL:
        raise ValueError(f"Pass at most {read.MAX_ELEMENTS_PER_CALL} elements in all.")
    port, target, rows = await edit._editable(client, guids, port)
    current = await _groups_of(client, port, guids)
    grouped = [g for g in guids if current[g]]
    if grouped:
        raise ValueError(f"Already in a group (ungroup it in Archicad first): {grouped}.")
    types = dict(zip(guids, (r.get("type") for r in rows), strict=True))
    items = [
        {
            "index": index,
            "status": "ready",
            "members": [{"element_guid": g, "type": types[g]} for g in group.element_guids],
            "parameters": {"elements": [{"elementId": {"guid": g}} for g in group.element_guids]},
        }
        for index, group in enumerate(groups)
    ]
    return {"operation": operation, "target": target, "items": items}


async def _dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    try:
        raw = await client.tapir(
            port,
            "CreateGroups",
            {"elementGroups": [i["parameters"] for i in items]},
            timeout=timeout,
        )
    except ArchicadError as exc:
        for item in items:
            item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Outcome is unknown. Inspect Archicad; do not retry this plan."
        return
    receipt["raw_response"] = raw
    rows = raw.get("groupGuids")
    if not isinstance(rows, list) or len(rows) != len(items):
        for item in items:
            item.update(status="unknown", error="Unexpected response cardinality.")
        return
    created = []
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        group = row.get("groupId") if isinstance(row, dict) else None
        guid = group.get("guid") if isinstance(group, dict) else None
        if isinstance(row, dict) and "error" in row:
            item.update(status="failed", error=row["error"])
        elif isinstance(guid, str):
            try:
                item["group_guid"] = str(UUID(guid)).upper()
            except ValueError:
                item.update(status="unknown", error="Invalid created group GUID.")
            else:
                item["status"] = "unverified"
                created.append(item)
        else:
            item.update(status="unknown", error="Missing group ID or error; inspect Archicad.")
    if not created:
        return
    try:
        rows = await _members(client, port, [i["group_guid"] for i in created], timeout)
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    for item, row in zip(created, rows, strict=True):
        found = _guids_of(row)
        item["after"] = found
        wanted = {m["element_guid"] for m in item["members"]}
        ok = found is not None and set(found) == wanted
        item["status"] = "verified" if ok else "verification_failed"
        if not ok:
            item["mismatches"] = ["elements"]


async def create_groups(
    client: ArchicadClient,
    groups: list[dict | GroupCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 groups of 2 or more editable, ungrouped elements."""
    if not 1 <= len(groups) <= MAX_GROUPS:
        raise ValueError(f"Pass between 1 and {MAX_GROUPS} groups.")
    validated = [g if isinstance(g, GroupCreate) else GroupCreate.model_validate(g) for g in groups]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_groups",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
