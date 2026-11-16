"""Graphic Overrides and Renovation Filters through the ArchicadMcpAberto add-on (addon/).

Neither Tapir 1.7 nor the official JSON API reach them. The Archicad 30 C API reads and
renames override rules, rule groups (the folders of the Graphic Override Rules dialog) and
combinations (renamed through rename_items), and only reads renovation filters: there is
no API call to rename a filter or read its settings. Model View Options cannot be renamed
by any API either (checked in the AC30 DevKit, 16/11/2026), so they are not here.
"""

from __future__ import annotations

from typing import Any

from archicad_mcp_aberto.connection import (
    AddOnError,
    ArchicadClient,
    CommandNotRegistered,
    resolve_port,
)
from archicad_mcp_aberto.tools import scenes


async def _addon(client, port, name, parameters=None, timeout=None) -> dict:
    try:
        return await client.own_addon(port, name, parameters, timeout=timeout)
    except CommandNotRegistered as exc:
        raise AddOnError(scenes.ADDON_MISSING, exc.code, exc.detail) from exc


def _guid(value: Any) -> str:
    return str(value).upper() if isinstance(value, str) else ""


def _named_rows(raw: Any, label: str) -> list[dict]:
    if not isinstance(raw, list) or not all(
        isinstance(r, dict) and _guid(r.get("guid")) and isinstance(r.get("name"), str) for r in raw
    ):
        raise ValueError(f"Unexpected {label} in the add-on response.")
    return raw


async def _overrides(client, port, timeout=None) -> dict:
    """{rule_groups, rules, combinations, current_combination}, names resolved."""
    raw = await _addon(client, port, "GetGraphicOverrides", {}, timeout)
    groups = _named_rows(raw.get("ruleGroups"), "rule groups")
    rules = _named_rows(raw.get("rules"), "rules")
    combinations = _named_rows(raw.get("combinations"), "combinations")
    rule_names = {_guid(r["guid"]): r["name"] for r in rules}
    group_names = {_guid(g["guid"]): g["name"] for g in groups}
    out_groups = [
        {
            "guid": _guid(g["guid"]),
            "name": g["name"],
            "rules": [rule_names.get(_guid(r), _guid(r)) for r in g.get("ruleGuids") or []],
        }
        for g in groups
    ]
    out_rules = [
        {
            "guid": _guid(r["guid"]),
            "name": r["name"],
            "rule_group": group_names.get(_guid(r.get("ruleGroupGuid"))),
        }
        for r in rules
    ]
    out_combinations = [
        {
            "guid": _guid(c["guid"]),
            "name": c["name"],
            "rules": [rule_names.get(_guid(r), _guid(r)) for r in c.get("ruleGuids") or []],
        }
        for c in combinations
    ]
    current = _guid(raw.get("currentCombinationGuid"))
    current_name = next((c["name"] for c in out_combinations if c["guid"] == current), None)
    return {
        "rule_groups": out_groups,
        "rules": out_rules,
        "combinations": out_combinations,
        "current_combination": current_name,
    }


async def list_graphic_overrides(client: ArchicadClient, port: int | None = None) -> dict:
    """Every Graphic Override rule group (folder), rule and combination by name, the rules
    of each folder and combination, and the current combination."""
    port = await resolve_port(client, port)
    return {"port": port, **await _overrides(client, port)}


async def list_renovation_filters(client: ArchicadClient, port: int | None = None) -> dict:
    """Every renovation filter by name and the current one. Read only."""
    port = await resolve_port(client, port)
    raw = await _addon(client, port, "GetRenovationFilters", {})
    rows = _named_rows(raw.get("renovationFilters"), "renovation filters")
    filters = [{"guid": _guid(r["guid"]), "name": r["name"]} for r in rows]
    current = _guid(raw.get("currentFilterGuid"))
    return {
        "port": port,
        "count": len(filters),
        "renovation_filters": filters,
        "current_filter": next((f["name"] for f in filters if f["guid"] == current), None),
        "note": "Renovation filters cannot be renamed by any Archicad API; rename by hand.",
    }
