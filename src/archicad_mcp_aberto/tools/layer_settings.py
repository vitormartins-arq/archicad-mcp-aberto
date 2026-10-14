"""Layer attributes and saved combination inventory, Tapir 1.7.0.

Changes target an existing layer GUID through CreateLayers overwriteExisting. Only the
requested flags/group and the unchanged required name are sent. No layer deletion or
renaming; the protected first layer is refused. Native attribute commands do not promise
Undo, so receipts keep prior values for a new preview/manual restoration.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Annotated
from uuid import UUID

from pydantic import Field, model_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError, resolve_port
from archicad_mcp_aberto.tools import drafting, layers, read, write

MAX_CHANGES = 50
REVERT_NOTE = (
    "Do not rely on Undo for layer attributes. "
    "Restore the before values manually or with a new preview/apply."
)


def _guid(value):
    try:
        return str(UUID(value["guid"])).upper()
    except (TypeError, KeyError, ValueError, AttributeError):
        return None


class LayerSettingsChange(write.InputModel):
    layer: Annotated[str, Field(min_length=1, max_length=255)]
    hidden: bool | None = None
    locked: bool | None = None
    wireframe: bool | None = None
    intersection_group: Annotated[int, Field(ge=0, le=32767)] | None = None

    @model_validator(mode="after")
    def fields_given(self):
        if not self.layer.strip():
            raise ValueError("layer must not be blank.")
        if not self.model_dump(exclude={"layer"}, exclude_none=True):
            raise ValueError("Supply at least one layer flag/group to change.")
        return self


def _pick(catalog, wanted):
    try:
        guid = str(UUID(wanted)).upper()
    except ValueError:
        guid = None
    found = (
        [r for r in catalog if r["attributeId"]["guid"].upper() == guid]
        if guid
        else [r for r in catalog if r["name"].casefold() == wanted.casefold()]
    )
    if len(found) != 1:
        problem = "is ambiguous" if found else "does not exist"
        raise ValueError(f"Layer {wanted!r} {problem}; pass its existing GUID.")
    return found[0]


async def list_layer_combinations(
    client: ArchicadClient,
    port: int | None = None,
    query: str | None = None,
    offset: int = 0,
    limit: int = 200,
    include_layers: bool = False,
) -> dict:
    """List saved layer combinations, filter/page first. include_layers adds native
    per-layer hidden/locked/wireframe/group states or an error per combination.
    """
    if type(offset) is not int or type(limit) is not int:
        raise ValueError("offset and limit must be integers.")
    read.page_args(offset, limit, 500)
    port = await resolve_port(client, port)
    headers = await drafting._attributes(client, port, "LayerCombination")
    if query:
        headers = [h for h in headers if query.casefold() in h["name"].casefold()]
    selected = headers[offset : offset + limit]
    items = [
        {
            "guid": str(UUID(h["attributeId"]["guid"])).upper(),
            "name": h["name"],
            "index": h.get("index"),
        }
        for h in selected
    ]
    if include_layers:
        for start in range(0, len(items), 100):
            batch = items[start : start + 100]
            raw = await client.tapir(
                port,
                "GetLayerCombinations",
                {"attributes": [{"attributeId": {"guid": item["guid"]}} for item in batch]},
            )
            rows = raw.get("layerCombinations")
            if not isinstance(rows, list) or len(rows) != len(batch):
                raise ValueError("Unexpected layer combination response cardinality.")
            for item, row in zip(batch, rows, strict=True):
                if isinstance(row, dict) and "error" in row:
                    item["error"] = row["error"]
                    continue
                combination = row.get("layerCombination") if isinstance(row, dict) else None
                if not isinstance(combination, dict) or not isinstance(
                    combination.get("layers"), list
                ):
                    raise ValueError("Unexpected layer combination details.")
                if _guid(combination.get("attributeId")) != item["guid"]:
                    raise ValueError("Unexpected layer combination GUID.")
                item["layers"] = combination["layers"]
    return {
        "port": port,
        "total": len(headers),
        "offset": offset,
        "limit": limit,
        "include_layers": include_layers,
        "items": items,
    }


async def _plan(client, changes, port, operation):
    port, target, _ = await write._context(client, port)
    catalog = await drafting._attributes(client, port, "Layer")
    headers = [_pick(catalog, change.layer) for change in changes]
    guids = [str(UUID(h["attributeId"]["guid"])).upper() for h in headers]
    if len(set(guids)) != len(guids):
        raise ValueError("Each layer may appear only once, including name/GUID aliases.")
    rows = await layers._details(client, port, guids)
    items = []
    for i, (change, guid, before) in enumerate(zip(changes, guids, rows, strict=True)):
        if not isinstance(before, dict) or "error" in before:
            raise ValueError(f"Cannot read layer {guid}.")
        if before.get("index") == 1:
            raise ValueError("The protected first (Archicad) layer is refused.")
        if _guid(before.get("attributeId")) != guid:
            raise ValueError("Unexpected layer GUID in details.")
        if any(k not in before for k in ("name", *layers.LAYER_FIELDS.values())):
            raise ValueError("Cannot read all current layer flags/group.")
        native = {
            layers.LAYER_FIELDS[k]: v
            for k, v in change.model_dump(exclude={"layer"}, exclude_none=True).items()
        }
        items.append(
            {
                "index": i,
                "status": "ready",
                "layer_guid": guid,
                "layer_name": before["name"],
                "before": deepcopy(before),
                "new": native,
                "expected": {**deepcopy(before), **native},
                "parameters": {"attributeId": {"guid": guid}, "name": before["name"], **native},
            }
        )
    return {"operation": operation, "target": target, "items": items, "revert_note": REVERT_NOTE}


async def _dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    try:
        raw = await client.tapir(
            port,
            "CreateLayers",
            {"layerDataArray": [i["parameters"] for i in items], "overwriteExisting": True},
            timeout=timeout,
        )
    except ArchicadError as exc:
        for item in items:
            item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Layer outcome unknown. Inspect Archicad; never retry this token."
        return
    receipt["raw_response"] = raw
    rows = raw.get("attributeIds")
    if not isinstance(rows, list) or len(rows) != len(items):
        for item in items:
            item.update(status="unknown", error="Unexpected layer response cardinality.")
        return
    good = []
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        if isinstance(row, dict) and "error" in row:
            item.update(status="failed", error=row["error"])
        elif isinstance(row, dict) and _guid(row.get("attributeId")) == item["layer_guid"]:
            item["status"] = "unverified"
            good.append(item)
        else:
            item.update(
                status="unknown",
                error="Missing or unexpected layer GUID; inspect possible native creation.",
            )
    if not good:
        return
    try:
        after = await layers._details(client, port, [i["layer_guid"] for i in good], timeout)
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    for item, row in zip(good, after, strict=True):
        item["after"] = row
        differences = write._mismatches(item["expected"], row)
        item["status"] = "verification_failed" if differences else "verified"
        if differences:
            item["mismatches"] = differences


async def set_layer_settings(
    client: ArchicadClient,
    changes: list[dict | LayerSettingsChange],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/edit up to 50 existing layer flags: hidden/locked/wireframe and
    intersection_group. Name/GUID/index and unspecified flags preserved; no renaming,
    deletion or intentional creation. Protected first layer refused. No guaranteed Undo;
    keep before values for a new preview/manual restore. Never saves.
    """
    if not 1 <= len(changes) <= MAX_CHANGES:
        raise ValueError(f"Pass between 1 and {MAX_CHANGES} layer changes.")
    entries = [
        c if isinstance(c, LayerSettingsChange) else LayerSettingsChange.model_validate(c)
        for c in changes
    ]
    return await write._write(
        client,
        entries,
        port,
        dry_run,
        confirmation_token,
        "set_layer_settings",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
