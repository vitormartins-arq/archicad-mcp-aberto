"""Zone categories: create new ones (Tapir 1.7.0 CreateZoneCategories).

create_zone_categories never overwrites: a name the project already has is refused in
the preview. Each new category gets a name, an optional code and an optional colour
(red, green and blue from 0 to 1). Tapir copies the zone stamp and its parameters from
the project's first zone category. The read-back is GetZoneCategories. Never saves.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import drafting, write

MAX_CATEGORIES = 50
Unit = Annotated[float, Field(ge=0, le=1)]


class Color(write.InputModel):
    red: Unit
    green: Unit
    blue: Unit


class ZoneCategoryCreate(write.InputModel):
    name: Annotated[str, Field(min_length=1, max_length=255)]
    code: Annotated[str, Field(max_length=255)] | None = None
    color: Color | None = None

    @field_validator("name")
    @classmethod
    def trimmed(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("zone category names must not start or end with spaces.")
        return value


async def _plan(client, categories, port, operation):
    port, target, _ = await write._context(client, port)
    rows = await drafting._attributes(client, port, "ZoneCategory")
    existing = {r["name"].casefold() for r in rows}
    seen = set()
    items = []
    for index, category in enumerate(categories):
        key = category.name.casefold()
        if key in existing:
            raise ValueError(
                f"Zone category {category.name!r} already exists; nothing is overwritten."
            )
        if key in seen:
            raise ValueError(f"Zone category {category.name!r} appears twice in this call.")
        seen.add(key)
        payload: dict[str, Any] = {"name": category.name}
        if category.code is not None:
            payload["categoryCode"] = category.code
        if category.color is not None:
            payload["color"] = category.color.model_dump()
        items.append({"index": index, "status": "ready", "parameters": payload})
    stamp_from = rows[0]["name"] if rows else None
    return {"operation": operation, "target": target, "stamp_from": stamp_from, "items": items}


async def _details(client, port, guids, timeout):
    response = await client.tapir(
        port,
        "GetZoneCategories",
        {
            "attributeIds": [{"attributeId": {"guid": g}} for g in guids],
            "fields": ["categoryCode", "color"],
        },
        timeout=timeout,
    )
    rows = response.get("zoneCategories")
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected zone category response cardinality.")
    return rows


def _mismatches(item: dict, row: Any) -> list[str]:
    p = item["parameters"]
    expected: dict[str, Any] = {"name": p["name"]}
    if "categoryCode" in p:
        expected["categoryCode"] = p["categoryCode"]
    differences = write._mismatches(expected, row)
    if "color" in p:
        found = row.get("color") if isinstance(row, dict) else None
        if not isinstance(found, dict) or any(
            not isinstance(found.get(k), int | float) or abs(found[k] - v) > 1e-3
            for k, v in p["color"].items()
        ):
            differences.append("color")
    return differences


async def _dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    try:
        raw = await client.tapir(
            port,
            "CreateZoneCategories",
            {"zoneCategoryDataArray": [i["parameters"] for i in items], "overwriteExisting": False},
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
                item["zone_category_guid"] = str(UUID(guid)).upper()
            except ValueError:
                item.update(status="unknown", error="Invalid created zone category GUID.")
            else:
                item["status"] = "unverified"
                created.append(item)
        else:
            item.update(status="unknown", error="Missing ID or error; inspect Archicad.")
    if not created:
        return
    try:
        after = await _details(client, port, [i["zone_category_guid"] for i in created], timeout)
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    for item, row in zip(created, after, strict=True):
        item["after"] = row
        differences = _mismatches(item, row)
        item["status"] = "verification_failed" if differences else "verified"
        if differences:
            item["mismatches"] = differences


async def create_zone_categories(
    client: ArchicadClient,
    categories: list[dict | ZoneCategoryCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 50 new zone categories (name, code, colour 0 to 1).

    An existing name is refused, never overwritten. The stamp comes from the project's
    first zone category, as Tapir does.
    """
    if not 1 <= len(categories) <= MAX_CATEGORIES:
        raise ValueError(f"Pass between 1 and {MAX_CATEGORIES} zone categories.")
    validated = [
        c if isinstance(c, ZoneCategoryCreate) else ZoneCategoryCreate.model_validate(c)
        for c in categories
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_zone_categories",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
