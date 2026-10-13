"""Layers: list them, create new ones and move elements to a layer (Tapir 1.7.0).

create_layers never overwrites: a name the project already has is refused in the preview.
set_element_layers moves editable elements to an existing layer by name. Both use the
shared preview, single-use token and receipts, and read back what Archicad stored.
Never saves.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError, resolve_port
from archicad_mcp_aberto.tools import drafting, edit, read, write

MAX_LAYERS = 50
MAX_MOVES = 100
# input field -> Tapir layer field
LAYER_FIELDS = {
    "hidden": "isHidden",
    "locked": "isLocked",
    "wireframe": "isWireframe",
    "intersection_group": "intersectionGroupNr",
}


async def _details(client, port, guids: list[str], timeout=None) -> list[Any]:
    rows = []
    extra = {} if timeout is None else {"timeout": timeout}
    for offset in range(0, len(guids), 100):
        batch = guids[offset : offset + 100]
        response = await client.tapir(
            port,
            "GetLayers",
            # No "fields": every flag comes back, and older builds reject the filter.
            {"attributeIds": [{"attributeId": {"guid": g}} for g in batch]},
            **extra,
        )
        found = response.get("layers")
        if not isinstance(found, list) or len(found) != len(batch):
            raise ValueError("Unexpected layer response cardinality.")
        rows += found
    return rows


async def list_layers(client: ArchicadClient, port: int | None = None) -> dict:
    port = await resolve_port(client, port)
    headers = await drafting._attributes(client, port, "Layer")
    guids = [str(UUID(r["attributeId"]["guid"])).upper() for r in headers]
    layers = await _details(client, port, guids) if guids else []
    return {"port": port, "total": len(layers), "layers": layers}


class LayerCreate(write.InputModel):
    name: Annotated[str, Field(min_length=1, max_length=255)]
    hidden: bool | None = None
    locked: bool | None = None
    wireframe: bool | None = None
    intersection_group: Annotated[int, Field(ge=0)] | None = None

    @field_validator("name")
    @classmethod
    def trimmed(cls, value: str) -> str:
        if value != value.strip() or not value:
            raise ValueError("layer names must not start or end with spaces.")
        return value


async def _create_plan(client, layers, port, operation):
    port, target, _ = await write._context(client, port)
    existing = {r["name"].casefold() for r in await drafting._attributes(client, port, "Layer")}
    seen = set()
    items = []
    for index, layer in enumerate(layers):
        key = layer.name.casefold()
        if key in existing:
            raise ValueError(f"Layer {layer.name!r} already exists; nothing is overwritten.")
        if key in seen:
            raise ValueError(f"Layer {layer.name!r} appears twice in this call.")
        seen.add(key)
        payload: dict[str, Any] = {"name": layer.name}
        for field_name, tapir_name in LAYER_FIELDS.items():
            value = getattr(layer, field_name)
            if value is not None:
                payload[tapir_name] = value
        items.append({"index": index, "status": "ready", "parameters": payload})
    return {"operation": operation, "target": target, "items": items}


async def _create_dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    try:
        raw = await client.tapir(
            port,
            "CreateLayers",
            {"layerDataArray": [i["parameters"] for i in items], "overwriteExisting": False},
            timeout=timeout,
        )
    except ArchicadError as exc:
        for item in items:
            item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Outcome is unknown. Inspect Archicad; do not retry this plan."
        return
    receipt["raw_response"] = raw
    rows = raw.get("attributeIds")
    if not isinstance(rows, list) or len(rows) != len(items):
        for item in items:
            item.update(status="unknown", error="Unexpected response cardinality.")
        return
    created = []
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        identifier = row.get("attributeId") if isinstance(row, dict) else None
        guid = identifier.get("guid") if isinstance(identifier, dict) else None
        if isinstance(row, dict) and "error" in row:
            item.update(status="failed", error=row["error"])
        elif isinstance(guid, str):
            try:
                item["layer_guid"] = str(UUID(guid)).upper()
            except ValueError:
                item.update(status="unknown", error="Invalid created layer GUID.")
            else:
                item["status"] = "unverified"
                created.append(item)
        else:
            item.update(status="unknown", error="Missing layer ID or error; inspect Archicad.")
    if not created:
        return
    try:
        after = await _details(client, port, [i["layer_guid"] for i in created], timeout)
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    for item, row in zip(created, after, strict=True):
        item["after"] = row
        differences = write._mismatches(item["parameters"], row)
        item["status"] = "verification_failed" if differences else "verified"
        if differences:
            item["mismatches"] = differences


async def create_layers(
    client: ArchicadClient,
    layers: list[dict | LayerCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 50 new layers; an existing name is refused, never overwritten."""
    if not 1 <= len(layers) <= MAX_LAYERS:
        raise ValueError(f"Pass between 1 and {MAX_LAYERS} layers.")
    validated = [x if isinstance(x, LayerCreate) else LayerCreate.model_validate(x) for x in layers]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_layers",
        planner_override=_create_plan,
        dispatcher_override=_create_dispatch,
    )


class LayerMove(write.InputModel):
    element_guid: str
    layer: Annotated[str, Field(min_length=1, max_length=255)]

    @field_validator("element_guid")
    @classmethod
    def canonical_guid(cls, value: str) -> str:
        return str(UUID(value)).upper()


async def _move_plan(client, moves, port, operation):
    guids = [m.element_guid for m in moves]
    port, target, rows = await edit._editable(client, guids, port)
    layers = await drafting._attributes(client, port, "Layer")
    items = []
    for index, (move, row) in enumerate(zip(moves, rows, strict=True)):
        try:
            layer = drafting._named(layers, move.layer, "Layer")
        except ValueError as exc:
            raise ValueError(f"Change {index} ({move.element_guid}): {exc}") from None
        items.append(
            {
                "index": index,
                "status": "ready",
                "element_guid": move.element_guid,
                "elementType": row.get("type"),
                "floorIndex": row.get("floorIndex"),
                "layerIndex": row.get("layerIndex"),
                "new_layer": {"index": layer["index"], "name": layer["name"]},
                "unchanged": row.get("layerIndex") == layer["index"],
                "parameters": {
                    "elementId": {"guid": move.element_guid},
                    "details": {"layerIndex": layer["index"]},
                },
            }
        )
    return {"operation": operation, "target": target, "items": items}


async def _verify_moves(client, receipt, items):
    response = await client.tapir(
        receipt["target"]["port"],
        "GetDetailsOfElements",
        {
            "elements": read.element_ids([i["element_guid"] for i in items]),
            "fields": write.DETAIL_FIELDS,
        },
        timeout=receipt["write_timeout_seconds"],
    )
    rows = response.get("detailsOfElements")
    if not isinstance(rows, list) or len(rows) != len(items):
        raise ValueError("Unexpected element details response.")
    for item, row in zip(items, rows, strict=True):
        item["after"] = {k: row.get(k) for k in ("type", "floorIndex", "layerIndex")}
        wanted = item["parameters"]["details"]["layerIndex"]
        differences = write._mismatches(
            {"layerIndex": wanted, "type": item["elementType"], "floorIndex": item["floorIndex"]},
            row,
        )
        item["status"] = "verification_failed" if differences else "verified"
        if differences:
            item["mismatches"] = differences


async def _move_dispatch(client, receipt):
    await edit._execute(
        client, receipt, "SetDetailsOfElements", "elementsWithDetails", _verify_moves
    )


async def set_element_layers(
    client: ArchicadClient,
    changes: list[dict | LayerMove],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply moving up to 100 editable elements to existing layers by name."""
    validated = [c if isinstance(c, LayerMove) else LayerMove.model_validate(c) for c in changes]
    edit._unique([c.element_guid for c in validated], MAX_MOVES)
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "set_element_layers",
        planner_override=_move_plan,
        dispatcher_override=_move_dispatch,
    )
