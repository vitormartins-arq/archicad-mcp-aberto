"""Grid lines (Grid Tool elements) through the ArchicadMcpAberto add-on (addon/).

Tapir has grid commands only after 1.7.2, so GetGridElementDefaults, GetGridElements and
CreateGridElements were ported to our add-on (Vitor, 21/10/2026: do not wait for Tapir).

list_grid_elements reads every grid line: start point, angle, length, story, layer and,
optionally, its GDL parameters. create_grid_elements draws grid lines from a start and
an end point on a story, with an optional layer and GDL parameters by name (the bubble
text, for example). The preview checks every parameter name and value type against the
tool defaults; the length always comes from the two points. One add-on call makes the
whole batch in one Undo step, and each new grid line is read back. Never saves.
"""

from __future__ import annotations

import math
from typing import Annotated, Any

from pydantic import Field, field_validator, model_validator

from archicad_mcp_aberto.connection import (
    AddOnError,
    ArchicadClient,
    ArchicadError,
    CommandNotRegistered,
    resolve_port,
)
from archicad_mcp_aberto.tools import drafting, scenes, solids, write

MAX_GRIDS = 50
MAX_PARAMETERS = 50
TOLERANCE = 1e-4  # metres and radians
NUMERIC = {
    "Integer", "Length", "Angle", "RealNum", "LightSwitch", "ColorRGB", "Intensity",
    "LineType", "Material", "FillPattern", "PenColor", "Boolean", "BuildingMaterial",
    "Profile",
}  # fmt: skip
TEXT = {"String", "Title"}
# Set from the two points by the add-on (AC_Length, or A for a part without it).
LENGTH_PARAMETERS = {"ac_length", "a"}
Name = Annotated[str, Field(min_length=1, max_length=255)]


class GridParameter(write.InputModel):
    name: Annotated[str, Field(min_length=1, max_length=32)]
    value: bool | float | str

    @field_validator("value")
    @classmethod
    def finite(cls, value: bool | float | str) -> bool | float | str:
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("must be finite.")
        return value


class GridCreate(write.InputModel):
    start: write.Point
    end: write.Point
    floor_index: int
    layer: Name | None = None
    parameters: Annotated[list[GridParameter], Field(max_length=MAX_PARAMETERS)] = []

    @model_validator(mode="after")
    def sound(self) -> GridCreate:
        if math.hypot(self.end.x - self.start.x, self.end.y - self.start.y) < 1e-6:
            raise ValueError("A grid line needs different start and end points.")
        names = [p.name.casefold() for p in self.parameters]
        if len(set(names)) != len(names):
            raise ValueError("A parameter appears twice.")
        if LENGTH_PARAMETERS & set(names):
            raise ValueError("The length comes from start and end; do not pass AC_Length or A.")
        return self


async def _addon(client, port, name, parameters=None, timeout=None):
    try:
        return await client.own_addon(port, name, parameters, timeout=timeout)
    except CommandNotRegistered as exc:
        raise AddOnError(scenes.ADDON_MISSING, exc.code, exc.detail) from exc


def _row(raw: dict) -> dict:
    pos = raw.get("pos") or {}
    out = {
        "guid": str((raw.get("elementId") or {}).get("guid", "")).upper(),
        "start": {"x": pos.get("x"), "y": pos.get("y")},
        "angle": raw.get("angle"),
        "length": raw.get("length"),
        "floor_index": raw.get("floorIndex"),
        "layer_index": raw.get("layerIndex"),
        "library_part": raw.get("libraryPartName"),
    }
    if (
        all(isinstance(v, int | float) for v in (pos.get("x"), pos.get("y")))
        and isinstance(out["angle"], int | float)
        and isinstance(out["length"], int | float)
    ):
        out["end"] = {
            "x": pos["x"] + out["length"] * math.cos(out["angle"]),
            "y": pos["y"] + out["length"] * math.sin(out["angle"]),
        }
    if "parameters" in raw:
        out["parameters"] = raw["parameters"]
    return out


async def _grids(client, port, include_parameters=False, timeout=None) -> list[dict]:
    response = await _addon(
        client, port, "GetGridElements", {"includeParameters": include_parameters}, timeout
    )
    rows = response.get("gridElements")
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise ValueError("Unexpected grid elements response.")
    return [_row(r) for r in rows]


async def list_grid_elements(
    client: ArchicadClient, port: int | None = None, include_parameters: bool = False
) -> dict:
    """Every grid line: start, end, angle, length, story, layer, library part; with
    include_parameters, also the GDL parameters and the Grid Tool defaults."""
    port = await resolve_port(client, port)
    rows = await _grids(client, port, include_parameters)
    result: dict[str, Any] = {"port": port, "count": len(rows), "grid_elements": rows}
    if include_parameters:
        defaults = _row(await _addon(client, port, "GetGridElementDefaults"))
        for key in ("guid", "start", "end", "angle", "length"):
            defaults.pop(key, None)
        result["tool_defaults"] = defaults
    return result


def _check_parameters(grid: GridCreate, known: dict[str, dict], label: str) -> list[dict]:
    out = []
    for p in grid.parameters:
        row = known.get(p.name.casefold())
        if row is None:
            raise ValueError(f"{label}: the grid tool has no parameter {p.name!r}.")
        kind = row.get("type")
        if "dimension1" in row or (kind not in NUMERIC and kind not in TEXT):
            raise ValueError(f"{label}: parameter {row['name']!r} ({kind}) cannot be set here.")
        if (kind in TEXT) != isinstance(p.value, str):
            wanted = "text" if kind in TEXT else "a number or boolean"
            raise ValueError(f"{label}: parameter {row['name']!r} needs {wanted}.")
        out.append({"name": row["name"], "value": p.value})
    return out


async def _plan(client, grids, port, operation):
    port, target, floors = await write._context(client, port)
    defaults = await _addon(client, port, "GetGridElementDefaults")
    known = {
        str(r.get("name", "")).casefold(): r
        for r in defaults.get("parameters", [])
        if isinstance(r, dict)
    }
    layers = None
    items = []
    for index, grid in enumerate(grids):
        label = f"Grid {index}"
        if grid.floor_index not in floors:
            raise ValueError(f"{label}: story {grid.floor_index} does not exist.")
        dx, dy = grid.end.x - grid.start.x, grid.end.y - grid.start.y
        payload: dict[str, Any] = {
            "begCoordinate": grid.start.model_dump(),
            "endCoordinate": grid.end.model_dump(),
            "floorIndex": grid.floor_index,
        }
        entry: dict[str, Any] = {
            "index": index,
            "status": "ready",
            "length": math.hypot(dx, dy),
            "angle": math.atan2(dy, dx),
        }
        if grid.layer is not None:
            layers = layers if layers is not None else await drafting._attributes(
                client, port, "Layer")  # fmt: skip
            try:
                layer = drafting._named(layers, grid.layer, "Layer")
            except ValueError as exc:
                raise ValueError(f"{label}: {exc}") from None
            payload["layerIndex"] = layer["index"]
            entry["layer_name"] = layer["name"]
        if grid.parameters:
            payload["parameters"] = _check_parameters(grid, known, label)
        entry["parameters"] = payload
        items.append(entry)
    return {
        "operation": operation,
        "target": target,
        "library_part": defaults.get("libraryPartName"),
        "items": items,
    }


def _mismatches(item: dict, row: dict | None) -> list[str]:
    if row is None:
        return ["missing"]
    p = item["parameters"]
    problems = []
    start = row["start"]
    if not all(
        isinstance(start[k], int | float) and abs(start[k] - p["begCoordinate"][k]) <= TOLERANCE
        for k in ("x", "y")
    ):
        problems.append("start")
    angle = row["angle"]
    if (
        not isinstance(angle, int | float)
        or abs(math.remainder(angle - item["angle"], math.tau)) > TOLERANCE
    ):
        problems.append("angle")
    length = row["length"]
    if not isinstance(length, int | float) or abs(length - item["length"]) > TOLERANCE:
        problems.append("length")
    if row["floor_index"] != p["floorIndex"]:
        problems.append("floor_index")
    if "layerIndex" in p and row["layer_index"] != p["layerIndex"]:
        problems.append("layer")
    found = {str(r.get("name")): r.get("value") for r in row.get("parameters", [])}
    for wanted in p.get("parameters", []):
        value = found.get(wanted["name"])
        if isinstance(wanted["value"], str):
            ok = value == wanted["value"]
        else:
            ok = isinstance(value, int | float) and abs(value - float(wanted["value"])) <= 1e-6
        if not ok:
            problems.append(f"parameter {wanted['name']}")
    return problems


async def _dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    receipt["undo_scope"] = "The whole batch is one Undo step (Create Grid Elements)."
    try:
        raw = await _addon(
            client,
            port,
            "CreateGridElements",
            {"gridElements": [i["parameters"] for i in items]},
            timeout,
        )
    except AddOnError as exc:
        # The add-on answered with an error (or is not loaded): nothing was made.
        for item in items:
            item.update(status="failed", error=exc.detail or str(exc))
        return
    except ArchicadError as exc:
        return solids._unknown(receipt, f"CreateGridElements: {exc}")
    rows = raw.get("elements")
    if not isinstance(rows, list) or len(rows) != len(items):
        return solids._unknown(receipt, "Unexpected CreateGridElements response.")
    receipt["raw_response"] = raw
    if raw.get("warnings"):
        receipt["warnings"] = raw["warnings"]
    created = []
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        if isinstance(row, dict) and "error" in row:
            item.update(status="failed", error=row["error"])
            continue
        guid = (row.get("elementId") or {}).get("guid") if isinstance(row, dict) else None
        if not isinstance(guid, str):
            item.update(status="unknown", error="Missing ID or error; inspect Archicad.")
            continue
        item.update(status="unverified", element_guid=guid.upper())
        created.append(item)
    if not created:
        return
    try:
        include = any("parameters" in i["parameters"] for i in created)
        after = {r["guid"]: r for r in await _grids(client, port, include, timeout)}
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    for item in created:
        row = after.get(item["element_guid"])
        item["after"] = row
        problems = _mismatches(item, row)
        item["status"] = "verification_failed" if problems else "verified"
        if problems:
            item["mismatches"] = problems


async def create_grid_elements(
    client: ArchicadClient,
    grids: list[dict | GridCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 50 grid lines, each from start to end on a story, with an
    optional layer and GDL parameters by name."""
    if not 1 <= len(grids) <= MAX_GRIDS:
        raise ValueError(f"Pass between 1 and {MAX_GRIDS} grid lines.")
    validated = [g if isinstance(g, GridCreate) else GridCreate.model_validate(g) for g in grids]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_grid_elements",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
