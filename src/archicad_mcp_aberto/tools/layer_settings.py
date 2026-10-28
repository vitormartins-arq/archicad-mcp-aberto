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


class LayerCombinationLayer(write.InputModel):
    layer: Annotated[str, Field(min_length=1, max_length=255)]
    visible: bool = True
    locked: bool = False
    wireframe: bool = False
    intersection_group: Annotated[int, Field(ge=0, le=32767)] = 1


class LayerCombinationCreate(write.InputModel):
    name: Annotated[str, Field(min_length=1, max_length=255)]
    layers: list[LayerCombinationLayer]

    @model_validator(mode="after")
    def valid_combination(self):
        if not self.name.strip():
            raise ValueError("name must not be blank.")
        if not self.layers:
            raise ValueError("layers must not be empty.")
        return self


async def _plan_layer_combinations(client, combinations, port, operation):
    port, target, _ = await write._context(client, port)
    existing = await drafting._attributes(client, port, "LayerCombination")
    existing_names = {row["name"].casefold() for row in existing}
    layer_catalog = await drafting._attributes(client, port, "Layer")
    requested_names: set[str] = set()
    items = []
    for index, combination in enumerate(combinations):
        name = combination.name.strip()
        folded = name.casefold()
        if folded in existing_names or folded in requested_names:
            raise ValueError(f"Layer combination {name!r} already exists or is duplicated.")
        requested_names.add(folded)
        selected = [_pick(layer_catalog, entry.layer) for entry in combination.layers]
        guids = [str(UUID(row["attributeId"]["guid"])).upper() for row in selected]
        if len(set(guids)) != len(guids):
            raise ValueError(f"Layer combination {name!r} contains a duplicate layer.")
        native_layers = [
            {
                "attributeId": {"guid": guid},
                "isHidden": not entry.visible,
                "isLocked": entry.locked,
                "isWireframe": entry.wireframe,
                "intersectionGroupNr": entry.intersection_group,
            }
            for entry, guid in zip(combination.layers, guids, strict=True)
        ]
        items.append(
            {
                "index": index,
                "status": "ready",
                "name": name,
                "parameters": {"name": name, "layers": native_layers},
                "expected_layers": native_layers,
            }
        )
    return {"operation": operation, "target": target, "items": items}


async def _dispatch_layer_combinations(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    try:
        raw = await client.tapir(
            port,
            "CreateLayerCombinations",
            {"layerCombinationDataArray": [item["parameters"] for item in items]},
            timeout=timeout,
        )
    except ArchicadError as exc:
        for item in items:
            item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Creation outcome unknown. Inspect Archicad; do not retry this token."
        return
    rows = raw.get("attributeIds")
    if not isinstance(rows, list) or len(rows) != len(items):
        for item in items:
            item.update(status="unknown", error="Unexpected creation response cardinality.")
        return
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        if isinstance(row, dict) and "error" in row:
            item.update(status="failed", error=row["error"])
        elif _guid(row.get("attributeId") if isinstance(row, dict) else None):
            item["created_guid"] = _guid(row["attributeId"])
            item["status"] = "unverified"
        else:
            item.update(status="unknown", error="Missing created layer-combination GUID.")
    try:
        after = await list_layer_combinations(client, port, include_layers=True)
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    by_name = {row["name"].casefold(): row for row in after["items"]}
    for item in items:
        if item["status"] != "unverified":
            continue
        found = by_name.get(item["name"].casefold())
        item["after"] = found
        if found is None or found.get("guid") != item["created_guid"]:
            item.update(status="verification_failed", mismatches=["name/guid"])
            continue
        expected = {row["attributeId"]["guid"]: row for row in item["expected_layers"]}
        actual = {row["attributeId"]["guid"]: row for row in found.get("layers", [])}
        mismatches = [guid for guid, value in expected.items() if actual.get(guid) != value]
        item["status"] = "verification_failed" if mismatches else "verified"
        if mismatches:
            item["mismatches"] = mismatches


async def create_layer_combinations(
    client: ArchicadClient,
    combinations: list[dict | LayerCombinationCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/create up to 20 new combinations; never overwrites, deletes or saves."""
    if not 1 <= len(combinations) <= 20:
        raise ValueError("Pass between 1 and 20 layer combinations.")
    validated = [
        row
        if isinstance(row, LayerCombinationCreate)
        else LayerCombinationCreate.model_validate(row)
        for row in combinations
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_layer_combinations",
        planner_override=_plan_layer_combinations,
        dispatcher_override=_dispatch_layer_combinations,
    )
