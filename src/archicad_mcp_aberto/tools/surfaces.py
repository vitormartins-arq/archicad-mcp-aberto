"""New surfaces copied from an existing one (Tapir 1.7.0 CreateSurfaces).

Tapir 1.7.0 starts a new surface from a zeroed record, so every field it is not given is
0 (black, no reflection). create_surfaces therefore copies every field of an existing
surface (GetSurfaces) and changes only what is asked: colour, transparency, surface
type, or dropping the texture. A name the project already has is refused, and nothing is
overwritten. The read-back compares every sent field. Never saves.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import drafting, solids, write, zone_categories

MAX_SURFACES = 50
FIELDS = [
    "materialType",
    "ambientReflection",
    "diffuseReflection",
    "specularReflection",
    "transparency",
    "shine",
    "transparencyAttenuation",
    "emissionAttenuation",
    "surfaceColor",
    "specularColor",
    "emissionColor",
    "fillId",
    "texture",
]
COLORS = ("surfaceColor", "specularColor", "emissionColor")
SurfaceType = Literal[
    "General", "Simple", "Matte", "Metal", "Plastic", "Glass", "Glowing", "Constant"
]


class SurfaceCreate(write.InputModel):
    name: Annotated[str, Field(min_length=1, max_length=255)]
    based_on: Annotated[str, Field(min_length=1, max_length=255)]  # an existing surface name
    color: zone_categories.Color | None = None
    transparency: Annotated[int, Field(ge=0, le=100)] | None = None
    material_type: SurfaceType | None = None
    keep_texture: bool = True

    @field_validator("name")
    @classmethod
    def trimmed(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("surface names must not start or end with spaces.")
        return value


async def _details(client, port, guids, timeout=None) -> list[dict]:
    extra = {} if timeout is None else {"timeout": timeout}
    response = await client.tapir(
        port,
        "GetSurfaces",
        {"attributeIds": [{"attributeId": {"guid": g}} for g in guids], "fields": FIELDS},
        **extra,
    )
    rows = response.get("surfaces")
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected surface details response.")
    return rows


def _copy(base: dict, surface: SurfaceCreate) -> dict:
    data: dict[str, Any] = {"name": surface.name}
    for key in FIELDS:
        if key in base:
            data[key] = base[key]
    for key in FIELDS[1:8]:  # the percentages and factors Tapir stores as whole numbers
        if isinstance(data.get(key), int | float):
            data[key] = round(data[key])
    texture = data.get("texture")
    if not surface.keep_texture or not isinstance(texture, dict) or not texture.get("name"):
        # An empty texture name would still link a texture in Tapir 1.7.0.
        data.pop("texture", None)
    if surface.color is not None:
        data["surfaceColor"] = surface.color.model_dump()
    if surface.transparency is not None:
        data["transparency"] = surface.transparency
    if surface.material_type is not None:
        data["materialType"] = surface.material_type
    return data


async def _plan(client, surfaces, port, operation):
    port, target, _ = await write._context(client, port)
    rows = await drafting._attributes(client, port, "Surface")
    existing = {r["name"].casefold() for r in rows}
    bases = {}
    for surface in surfaces:
        base = drafting._named(rows, surface.based_on, "Surface")
        bases[surface.based_on] = base
    guids = list(dict.fromkeys(b["attributeId"]["guid"] for b in bases.values()))
    details = dict(zip(guids, await _details(client, port, guids), strict=True))
    seen = set()
    items = []
    for index, surface in enumerate(surfaces):
        key = surface.name.casefold()
        if key in existing:
            raise ValueError(f"Surface {surface.name!r} already exists; nothing is overwritten.")
        if key in seen:
            raise ValueError(f"Surface {surface.name!r} appears twice in this call.")
        seen.add(key)
        base = bases[surface.based_on]
        row = details[base["attributeId"]["guid"]]
        if not isinstance(row, dict) or "error" in row:
            raise ValueError(f"Cannot read surface {base['name']!r}: {row}.")
        items.append(
            {
                "index": index,
                "status": "ready",
                "based_on": base["name"],
                "parameters": _copy(row, surface),
            }
        )
    return {"operation": operation, "target": target, "items": items}


def _mismatches(sent: dict, row: Any) -> list[str]:
    if not isinstance(row, dict):
        return ["missing"]
    problems = []
    for key, wanted in sent.items():
        found = row.get(key)
        if key in COLORS:
            ok = isinstance(found, dict) and all(
                isinstance(found.get(k), int | float) and abs(found[k] - v) <= 1e-3
                for k, v in wanted.items()
            )
        elif key == "texture":
            ok = isinstance(found, dict) and found.get("name") == wanted.get("name")
        elif isinstance(wanted, int | float) and not isinstance(wanted, bool):
            ok = isinstance(found, int | float) and abs(found - wanted) <= 0.5
        else:
            ok = found == wanted
        if not ok:
            problems.append(key)
    return problems


async def _dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    raw = await solids._results(
        client, port, "CreateSurfaces",
        {"surfaceDataArray": [i["parameters"] for i in items], "overwriteExisting": False},
        timeout,
    )  # fmt: skip
    rows = raw.get("attributeIds") if isinstance(raw, dict) else None
    if not isinstance(rows, list) or len(rows) != len(items):
        return solids._unknown(receipt, raw if isinstance(raw, str) else "Unexpected response.")
    receipt["raw_response"] = raw
    created = []
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        identifier = row.get("attributeId") if isinstance(row, dict) else None
        guid = identifier.get("guid") if isinstance(identifier, dict) else None
        if isinstance(row, dict) and "error" in row:
            item.update(status="failed", error=row["error"])
            continue
        try:
            item["surface_guid"] = str(UUID(guid)).upper()
        except (TypeError, ValueError):
            item.update(status="unknown", error="Missing ID or error; inspect Archicad.")
            continue
        item["status"] = "unverified"
        created.append(item)
    if not created:
        return
    try:
        after = await _details(client, port, [i["surface_guid"] for i in created], timeout)
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    for item, row in zip(created, after, strict=True):
        item["after"] = row
        problems = _mismatches(item["parameters"], row)
        item["status"] = "verification_failed" if problems else "verified"
        if problems:
            item["mismatches"] = problems


async def create_surfaces(
    client: ArchicadClient,
    surfaces: list[dict | SurfaceCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 50 new surfaces, each a copy of an existing surface with a
    new name and, optionally, another colour, transparency or type, or no texture."""
    if not 1 <= len(surfaces) <= MAX_SURFACES:
        raise ValueError(f"Pass between 1 and {MAX_SURFACES} surfaces.")
    validated = [
        s if isinstance(s, SurfaceCreate) else SurfaceCreate.model_validate(s) for s in surfaces
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_surfaces",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
