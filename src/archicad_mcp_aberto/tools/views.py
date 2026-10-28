"""Read view settings and safely change scale/layer combination (Tapir 1.7.0).

Navigator settings are not model-element edits. The native SetViewSettings command
has no undoable-command wrapper: receipts retain previous values, but do not promise
Archicad Undo. Restoration requires a new preview/apply or manual View Settings edits.
"""

from __future__ import annotations

import math
from copy import deepcopy
from typing import Annotated
from uuid import UUID

from pydantic import Field, model_validator

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port
from archicad_mcp_aberto.tools import drafting, edit, modify, navigator, renames, write

MAX_VIEWS = 100
REVERT_NOTE = (
    "Do not rely on Archicad Undo for Navigator settings. "
    "Previous values are in each receipt; restore manually or with a new preview/apply."
)


class ViewZoom(write.InputModel):
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @model_validator(mode="after")
    def ordered(self) -> ViewZoom:
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("zoom maximums must be greater than minimums")
        return self


class ViewSettingsChange(modify._Edit):
    drawing_scale: Annotated[int, Field(ge=1, le=1000000)] | None = None
    layer_combination: Annotated[str, Field(min_length=1, max_length=255)] | None = None
    zoom: ViewZoom | None = None
    rotation: Annotated[float, Field(ge=-math.tau, le=math.tau)] | None = None


def _guids(values):
    if not 1 <= len(values) <= MAX_VIEWS:
        raise ValueError(f"Pass between 1 and {MAX_VIEWS} view GUIDs.")
    guids = [str(UUID(g)).upper() for g in values]
    if len(set(guids)) != len(guids):
        raise ValueError("Each view may appear only once per call.")
    return guids


async def _settings(client, port, guids, timeout=None):
    response = await client.tapir(
        port,
        "GetViewSettings",
        {"navigatorItemIds": [{"navigatorItemId": {"guid": g}} for g in guids]},
        timeout=timeout,
    )
    rows = response.get("viewSettings")
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected view settings response cardinality.")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("Unexpected view settings response row.")
    return rows


async def get_view_settings(
    client: ArchicadClient,
    view_guids: list[str],
    port: int | None = None,
) -> dict:
    """Read settings or native errors per view (1–100 GUIDs). Rotation in radians,
    zoom in model metres; drawingScale is the denominator (100 means 1:100).
    """
    guids = _guids(view_guids)
    port = await resolve_port(client, port)
    rows = await _settings(client, port, guids)
    return {
        "port": port,
        "total": len(rows),
        "views": [
            {"guid": guid, **({"error": row["error"]} if "error" in row else {"settings": row})}
            for guid, row in zip(guids, rows, strict=True)
        ],
    }


def _combination(rows, wanted):
    try:
        guid = str(UUID(wanted)).upper()
    except ValueError:
        guid = None
    if guid:
        found = [r for r in rows if r.get("attributeId", {}).get("guid", "").upper() == guid]
    else:
        found = [r for r in rows if r["name"].casefold() == wanted.casefold()]
        if not found:
            found = [r for r in rows if r["name"].casefold() == wanted.strip().casefold()]
    if len(found) != 1:
        problem = "is ambiguous" if found else "does not exist"
        raise ValueError(
            f"Layer combination {wanted!r} {problem}; pass an existing combination GUID."
        )
    if sum(r["name"].casefold() == found[0]["name"].casefold() for r in rows) != 1:
        raise ValueError(
            "Tapir selects layer combinations by name; duplicate names cannot be resolved by GUID."
        )
    return found[0]


async def _plan(client, changes, port, operation):
    port, target, _ = await write._context(client, port)
    tree = await client.tapir(port, "GetNavigatorItemTree", {"navigatorMapId": "PublicViewMap"})
    nodes = {n["guid"]: n for n in navigator._flatten(tree.get("navigatorItemTree"))}
    guids = [c.guid for c in changes]
    if set(guids) - nodes.keys():
        raise ValueError("Every target must exist in the PublicViewMap; pass its view GUID.")
    rows = await _settings(client, port, guids)
    catalog = (
        await drafting._attributes(client, port, "LayerCombination")
        if any(c.layer_combination is not None for c in changes)
        else []
    )
    selected = {}
    items = []
    for i, (change, before) in enumerate(zip(changes, rows, strict=True)):
        if "error" in before:
            raise ValueError(
                f"Navigator item {change.guid} is not a readable view: {before['error']}"
            )
        native = {}
        if change.drawing_scale is not None:
            if type(before.get("drawingScale")) is not int:
                raise ValueError("Cannot read the current view drawing scale.")
            native["drawingScale"] = change.drawing_scale
        if change.layer_combination is not None:
            if not isinstance(before.get("layerCombination"), str):
                raise ValueError("Cannot read the current view layer combination.")
            row = _combination(catalog, change.layer_combination)
            native["layerCombination"] = row["name"]
            selected[row["attributeId"]["guid"].upper()] = row
        if change.zoom is not None:
            native["zoom"] = {
                "xMin": change.zoom.x_min,
                "yMin": change.zoom.y_min,
                "xMax": change.zoom.x_max,
                "yMax": change.zoom.y_max,
            }
        if change.rotation is not None:
            native["rotation"] = change.rotation
        expected = {**deepcopy(before), **native}
        if change.zoom is not None:
            expected["saveZoom"] = True
        items.append(
            {
                "index": i,
                "status": "ready",
                "view_guid": change.guid,
                "view_name": nodes[change.guid]["name"],
                "navigator_item": nodes[change.guid],
                "before": deepcopy(before),
                "new": change.model_dump(exclude={"guid"}, exclude_none=True),
                "expected": expected,
                "parameters": {"navigatorItemId": {"guid": change.guid}, "viewSettings": native},
            }
        )
    if selected:
        target["layer_combinations"] = sorted(
            selected.values(), key=lambda r: r["attributeId"]["guid"]
        )
        target["layer_combination_states"] = await renames._layer_states(
            client, port, sorted(selected)
        )
    return {
        "operation": operation,
        "target": target,
        "items": items,
        "revert_note": REVERT_NOTE,
        "scale_note": (
            "Setting drawing_scale enables the native stored-scale flag, "
            "which Tapir cannot read back."
        ),
    }


def _mismatches(expected, actual):
    wanted = {k: v for k, v in expected.items() if k != "rotation"}
    differences = write._mismatches(wanted, actual, "settings")
    if "rotation" in expected:
        angle = actual.get("rotation")
        if (
            not isinstance(angle, (float, int))
            or isinstance(angle, bool)
            or not math.isfinite(angle)
            or abs(math.remainder(angle - expected["rotation"], math.tau)) > 1e-7
        ):
            differences.append("settings.rotation")
    return differences


async def _verify(client, receipt, items):
    rows = await _settings(
        client,
        receipt["target"]["port"],
        [i["view_guid"] for i in items],
        receipt["write_timeout_seconds"],
    )
    for item, after in zip(items, rows, strict=True):
        item["after"] = after
        differences = _mismatches(item["expected"], after)
        item["status"] = "verification_failed" if differences else "verified"
        if differences:
            item["mismatches"] = differences
    # Assigning an existing combination must not edit its layer definitions.
    before_states = receipt["target"].get("layer_combination_states", {})
    if before_states:
        after_states = await renames._layer_states(
            client,
            receipt["target"]["port"],
            sorted(before_states),
            receipt["write_timeout_seconds"],
        )
        for item in items:
            if before_states != after_states:
                item["status"] = "verification_failed"
                item.setdefault("mismatches", []).append("layer_combination_states")


async def _dispatch(client, receipt):
    await edit._execute(
        client, receipt, "SetViewSettings", "navigatorItemIdsWithViewSettings", _verify
    )


async def set_view_settings(
    client: ArchicadClient,
    changes: list[dict | ViewSettingsChange],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/set scale, layer combination, zoom box in model metres and/or rotation
    in radians for up to 100 views. Preserves other readable settings and checks them
    after apply. No guaranteed Undo: restore from the receipt or View Settings. Never saves.
    """
    entries = [
        c if isinstance(c, ViewSettingsChange) else ViewSettingsChange.model_validate(c)
        for c in changes
    ]
    edit._unique([c.guid for c in entries], MAX_VIEWS)
    return await write._write(
        client,
        entries,
        port,
        dry_run,
        confirmation_token,
        "set_view_settings",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
