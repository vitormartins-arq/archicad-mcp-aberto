"""Favorites: list them by element type and apply them to existing elements (Tapir 1.7.0).

ApplyFavoritesToElements changes settings (structure, materials, pens, layer and the
like), classifications, categories and property values, never geometry. Tapir gives no
way to read a favorite's settings, so applied items stay "unverified": the receipt shows
the layer before and after, and the user checks the rest in Archicad. Never saves.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port
from archicad_mcp_aberto.tools import edit, read, write

MAX_APPLY = 50


async def _names(client, port, element_type: str) -> list[str]:
    response = await client.tapir(port, "GetFavoritesByType", {"elementType": element_type})
    names = response.get("favorites")
    if not isinstance(names, list):
        raise ValueError(f"Unexpected favorites response for {element_type}.")
    return [n for n in names if isinstance(n, str)]


async def list_favorites(
    client: ArchicadClient, element_type: str, port: int | None = None
) -> dict:
    port = await resolve_port(client, port)
    names = await _names(client, port, element_type)
    return {"port": port, "element_type": element_type, "total": len(names), "favorites": names}


def match(known: list[str], wanted: str) -> str | None:
    """The favorite's exact name, or None when missing; raises when ambiguous.

    Archicad 30 BRA ships favorites such as " Parede Genérica - Default" that start with a
    space. The exact name wins; otherwise case and outer spaces are ignored.
    """
    if wanted in known:
        return wanted
    found = [n for n in known if n.strip().casefold() == wanted.strip().casefold()]
    if len(found) > 1:
        raise ValueError(f"Favorite {wanted!r} is ambiguous: {', '.join(map(repr, found))}.")
    return found[0] if found else None


class FavoriteApply(write.InputModel):
    element_guid: str
    favorite: Annotated[str, Field(min_length=1, max_length=255)]

    @field_validator("element_guid")
    @classmethod
    def canonical_guid(cls, value: str) -> str:
        return str(UUID(value)).upper()


async def _plan(client, changes, port, operation):
    port, target, rows = await edit._editable(client, [c.element_guid for c in changes], port)
    by_type: dict[str, list[str]] = {}
    items = []
    for index, (change, row) in enumerate(zip(changes, rows, strict=True)):
        kind = row.get("type")
        if kind not in by_type:
            by_type[kind] = await _names(client, port, kind)
        try:
            name = match(by_type[kind], change.favorite)
        except ValueError as exc:
            raise ValueError(f"Change {index}: {kind} {exc}") from None
        if name is None:
            raise ValueError(f"Change {index}: {kind} favorite {change.favorite!r} does not exist.")
        items.append(
            {
                "index": index,
                "status": "ready",
                "element_guid": change.element_guid,
                "elementType": kind,
                "floorIndex": row.get("floorIndex"),
                "layerIndex": row.get("layerIndex"),
                "favorite": name,
                "parameters": {"elementId": {"guid": change.element_guid}, "favorite": name},
            }
        )
    return {"operation": operation, "target": target, "items": items}


async def _verify(client, receipt, items):
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
        differences = write._mismatches(
            {"type": item["elementType"], "floorIndex": item["floorIndex"]}, row
        )
        if differences:
            item.update(status="verification_failed", mismatches=differences)
        else:
            item["note"] = "Archicad reported success; favorite settings cannot be read back."


async def _dispatch(client, receipt):
    await edit._execute(client, receipt, "ApplyFavoritesToElements", "favoritesToApply", _verify)


async def apply_favorites(
    client: ArchicadClient,
    changes: list[dict | FavoriteApply],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply favorites by name to up to 50 editable elements of the same type."""
    validated = [
        c if isinstance(c, FavoriteApply) else FavoriteApply.model_validate(c) for c in changes
    ]
    edit._unique([c.element_guid for c in validated], MAX_APPLY)
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "apply_favorites",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )


# CreateFavoritesFromElements captures an element's settings, classifications, editable
# property values and memo as a NEW favorite of that element's type. Nothing is overwritten:
# a name that already exists for that type is refused. Locked and hotlinked elements are
# fine, since the element is only read.
MAX_CREATE = 50
FolderPart = Annotated[str, Field(min_length=1, max_length=255)]


class FavoriteFromElement(write.InputModel):
    element_guid: str
    favorite: Annotated[str, Field(min_length=1, max_length=255)]
    folder: Annotated[list[FolderPart], Field(max_length=10)] = []

    @field_validator("element_guid")
    @classmethod
    def canonical_guid(cls, value: str) -> str:
        return str(UUID(value)).upper()

    @field_validator("favorite")
    @classmethod
    def trimmed(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("must not start or end with spaces.")
        return value


async def _source_rows(client, guids, port):
    port, target, _ = await write._context(client, port)
    result = await client.tapir(
        port,
        "GetDetailsOfElements",
        {"elements": read.element_ids(guids), "fields": write.DETAIL_FIELDS},
    )
    rows = result.get("detailsOfElements")
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected element details response.")
    for guid, row in zip(guids, rows, strict=True):
        if not isinstance(row, dict) or "error" in row or row.get("type") in (None, "Unknown"):
            raise ValueError(f"Element {guid} does not exist or cannot be read.")
    return port, target, rows


async def _plan_create(client, items, port, operation):
    port, target, rows = await _source_rows(client, [i.element_guid for i in items], port)
    by_type: dict[str, list[str]] = {}
    seen: set[tuple[str, str]] = set()
    planned = []
    for index, (item, row) in enumerate(zip(items, rows, strict=True)):
        kind = row["type"]
        if kind not in by_type:
            by_type[kind] = await _names(client, port, kind)
        key = item.favorite.casefold()
        if any(n.strip().casefold() == key for n in by_type[kind]):
            raise ValueError(f"Favorite {index}: {kind} favorite {item.favorite!r} already exists.")
        if (kind, key) in seen:
            raise ValueError(f"Favorite {index}: {item.favorite!r} appears twice for {kind}.")
        seen.add((kind, key))
        parameters = {"elementId": {"guid": item.element_guid}, "favorite": item.favorite}
        if item.folder:
            parameters["folder"] = list(item.folder)
        planned.append(
            {
                "index": index,
                "status": "ready",
                "element_guid": item.element_guid,
                "elementType": kind,
                "favorite": item.favorite,
                "folder": list(item.folder),
                "parameters": parameters,
            }
        )
    return {"operation": operation, "target": target, "items": planned}


async def _verify_create(client, receipt, items):
    port = receipt["target"]["port"]
    names: dict[str, list[str]] = {}
    for item in items:
        kind = item["elementType"]
        if kind not in names:
            names[kind] = await _names(client, port, kind)
        if item["favorite"] in names[kind]:
            item["status"] = "verified"
        else:
            item.update(status="verification_failed", mismatches=["favorite_name"])


async def _dispatch_create(client, receipt):
    await edit._execute(
        client, receipt, "CreateFavoritesFromElements", "favoritesFromElements", _verify_create
    )


async def create_favorites_from_elements(
    client: ArchicadClient,
    favorites: list[dict | FavoriteFromElement],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/create up to 50 new favorites, each captured from one existing element."""
    if not 1 <= len(favorites) <= MAX_CREATE:
        raise ValueError(f"Pass between 1 and {MAX_CREATE} favorites.")
    validated = [
        f if isinstance(f, FavoriteFromElement) else FavoriteFromElement.model_validate(f)
        for f in favorites
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_favorites_from_elements",
        planner_override=_plan_create,
        dispatcher_override=_dispatch_create,
    )
