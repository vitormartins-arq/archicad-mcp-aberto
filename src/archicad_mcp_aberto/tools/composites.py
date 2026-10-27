"""Composites: create new ones (Tapir 1.7.0 CreateComposites).

create_composites never overwrites: a name the project already has is refused in the
preview. Each new composite has its skins (building material by name, thickness in
metres, Core, Finish or Other and a frame pen), what it may be used with (Wall, Slab,
Roof, Shell) and one separator line type and pen for every separator line.

Tapir silently leaves a skin's building material or a separator's line type at the
default when the given GUID is not found, so the preview resolves every name first and
the read-back (GetComposites) compares the GUIDs too. Never saves.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import drafting, write

MAX_COMPOSITES = 20
MAX_SKINS = 20
THICKNESS_TOLERANCE = 1e-6  # metres
Name = Annotated[str, Field(min_length=1, max_length=255)]
Pen = Annotated[int, Field(ge=1, le=255)]


class Skin(write.InputModel):
    building_material: Name
    thickness: Annotated[float, Field(gt=0, le=5)]
    type: Literal["Core", "Finish", "Other"] = "Core"
    pen: Pen = 1


class CompositeCreate(write.InputModel):
    name: Name
    use_with: Annotated[list[Literal["Wall", "Slab", "Roof", "Shell"]], Field(min_length=1)]
    skins: Annotated[list[Skin], Field(min_length=1, max_length=MAX_SKINS)]
    separator_line: Name | None = None
    separator_pen: Pen = 1

    @field_validator("name")
    @classmethod
    def trimmed(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("composite names must not start or end with spaces.")
        return value

    @field_validator("use_with")
    @classmethod
    def unique(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("use_with lists an element type twice.")
        return value


def _line(rows: list[dict], wanted: str | None) -> dict:
    if wanted is not None:
        return drafting._named(rows, wanted, "Line type")
    if not rows:
        raise ValueError("This project has no line types for the separators.")
    # Archicad's first line type is the solid line.
    return min(rows, key=lambda r: int(r.get("index", 0)))


async def _plan(client, composites, port, operation):
    port, target, _ = await write._context(client, port)
    existing = {r["name"].casefold() for r in await drafting._attributes(client, port, "Composite")}
    materials = await drafting._attributes(client, port, "BuildingMaterial")
    lines = await drafting._attributes(client, port, "Line")
    seen = set()
    items = []
    for index, composite in enumerate(composites):
        key = composite.name.casefold()
        if key in existing:
            raise ValueError(
                f"Composite {composite.name!r} already exists; nothing is overwritten."
            )
        if key in seen:
            raise ValueError(f"Composite {composite.name!r} appears twice in this call.")
        seen.add(key)
        line = _line(lines, composite.separator_line)
        skins = []
        for skin in composite.skins:
            material = drafting._named(materials, skin.building_material, "Building material")
            skins.append(
                {
                    "type": skin.type,
                    "buildingMaterialId": {"attributeId": dict(material["attributeId"])},
                    "framePen": skin.pen,
                    "thickness": skin.thickness,
                }
            )
        separator = {
            "lineTypeId": {"attributeId": dict(line["attributeId"])},
            "linePen": composite.separator_pen,
        }
        items.append(
            {
                "index": index,
                "status": "ready",
                "parameters": {
                    "name": composite.name,
                    "useWith": list(composite.use_with),
                    "skins": skins,
                    "separators": [dict(separator) for _ in range(len(skins) + 1)],
                },
                "building_materials": [s.building_material for s in composite.skins],
                "separator_line": line["name"],
                "total_thickness": round(sum(s.thickness for s in composite.skins), 9),
            }
        )
    return {"operation": operation, "target": target, "items": items}


async def _details(client, port, guids, timeout):
    response = await client.tapir(
        port,
        "GetComposites",
        {
            "attributeIds": [{"attributeId": {"guid": g}} for g in guids],
            "fields": ["useWith", "skins", "separators"],
        },
        timeout=timeout,
    )
    rows = response.get("composites")
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected composite response cardinality.")
    return rows


def _guid(value: Any) -> str | None:
    identifier = value.get("attributeId") if isinstance(value, dict) else None
    guid = identifier.get("guid") if isinstance(identifier, dict) else None
    return guid.upper() if isinstance(guid, str) else None


def _mismatches(item: dict, row: Any) -> list[str]:
    if not isinstance(row, dict) or "error" in row:
        return ["composite"]
    p = item["parameters"]
    differences = []
    if row.get("name") != p["name"]:
        differences.append("name")
    if sorted(row.get("useWith") or []) != sorted(p["useWith"]):
        differences.append("useWith")
    found = row.get("skins")
    if not isinstance(found, list) or len(found) != len(p["skins"]):
        differences.append("skins")
    else:
        for n, (want, got) in enumerate(zip(p["skins"], found, strict=True)):
            if not isinstance(got, dict):
                differences.append(f"skins[{n}]")
                continue
            for key in ("type", "framePen"):
                if got.get(key) != want[key]:
                    differences.append(f"skins[{n}].{key}")
            thickness = got.get("thickness")
            if (
                not isinstance(thickness, int | float)
                or abs(thickness - want["thickness"]) > THICKNESS_TOLERANCE
            ):
                differences.append(f"skins[{n}].thickness")
            if _guid(got.get("buildingMaterialId")) != _guid(want["buildingMaterialId"]):
                differences.append(f"skins[{n}].buildingMaterialId")
    found = row.get("separators")
    if not isinstance(found, list) or len(found) != len(p["separators"]):
        differences.append("separators")
    else:
        for n, (want, got) in enumerate(zip(p["separators"], found, strict=True)):
            if not isinstance(got, dict) or got.get("linePen") != want["linePen"]:
                differences.append(f"separators[{n}].linePen")
            elif _guid(got.get("lineTypeId")) != _guid(want["lineTypeId"]):
                differences.append(f"separators[{n}].lineTypeId")
    return differences


async def _dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    try:
        raw = await client.tapir(
            port,
            "CreateComposites",
            {"compositeDataArray": [i["parameters"] for i in items], "overwriteExisting": False},
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
        guid = _guid(row)
        if isinstance(row, dict) and "error" in row:
            item.update(status="failed", error=row["error"])
        elif guid is not None:
            try:
                item["composite_guid"] = str(UUID(guid)).upper()
            except ValueError:
                item.update(status="unknown", error="Invalid created composite GUID.")
            else:
                item["status"] = "unverified"
                created.append(item)
        else:
            item.update(status="unknown", error="Missing ID or error; inspect Archicad.")
    if not created:
        return
    try:
        after = await _details(client, port, [i["composite_guid"] for i in created], timeout)
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    for item, row in zip(created, after, strict=True):
        item["after"] = row
        differences = _mismatches(item, row)
        item["status"] = "verification_failed" if differences else "verified"
        if differences:
            item["mismatches"] = differences


async def create_composites(
    client: ArchicadClient,
    composites: list[dict | CompositeCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 new composites: skins by building material name.

    An existing name is refused, never overwritten. The separator line type defaults to
    the project's first line type (the solid line).
    """
    if not 1 <= len(composites) <= MAX_COMPOSITES:
        raise ValueError(f"Pass between 1 and {MAX_COMPOSITES} composites.")
    validated = [
        c if isinstance(c, CompositeCreate) else CompositeCreate.model_validate(c)
        for c in composites
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_composites",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
