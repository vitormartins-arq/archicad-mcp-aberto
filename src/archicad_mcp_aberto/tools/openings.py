"""Windows and doors placed into existing straight walls (Tapir CreateWindows/CreateDoors).

Tapir 1.7.0 takes no library part name for these: the Window or Door tool default
decides the part, or a named favorite applied to that tool first. The preview checks
the favorite exists; the receipt reports the part Archicad actually placed.
"""

from __future__ import annotations

import math
from typing import Annotated, Any
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import edit, write
from archicad_mcp_aberto.tools import favorites as favorites_tool

MAX_OPENINGS = 20
# operation -> element type, as Tapir names it in GetDetailsOfElements and GetFavoritesByType
KINDS = {"create_windows": "Window", "create_doors": "Door"}


class OpeningCreate(write.InputModel):
    wall_guid: str
    center_offset: Annotated[float, Field(ge=0)]
    sill_height: float | None = None
    width: write.Positive | None = None
    height: write.Positive | None = None
    favorite_name: Annotated[str, Field(min_length=1, max_length=255)] | None = None

    @field_validator("wall_guid")
    @classmethod
    def canonical_guid(cls, value: str) -> str:
        return str(UUID(value)).upper()

    @field_validator("favorite_name")
    @classmethod
    def visible_name(cls, value: str | None) -> str | None:
        # Kept exactly: live AC30 BRA favorites such as " Porta de Abrir em Madeira - Default"
        # start with a space, and Tapir looks the favorite up by its exact name.
        if value is not None and not value.strip():
            raise ValueError("favorite_name must not be blank.")
        return value


def _payload(opening: OpeningCreate) -> dict:
    payload: dict[str, Any] = {
        "ownerWallId": {"guid": opening.wall_guid},
        "centerOffset": opening.center_offset,
    }
    for key, value in (
        ("sillHeight", opening.sill_height),
        ("width", opening.width),
        ("height", opening.height),
        ("favoriteName", opening.favorite_name),
    ):
        if value is not None:
            payload[key] = value
    return payload


async def _plan(client, openings, port, operation):
    kind = KINDS[operation]
    walls = list(dict.fromkeys(o.wall_guid for o in openings))
    # A new opening edits its wall, so the wall must be editable and not hotlinked.
    port, target, rows = await edit._editable(client, walls, port)
    by_guid = dict(zip(walls, rows, strict=True))
    favorites = {o.favorite_name for o in openings if o.favorite_name}
    exact: dict[str, str] = {}
    if favorites:
        response = await client.tapir(port, "GetFavoritesByType", {"elementType": kind})
        known = response.get("favorites")
        if not isinstance(known, list):
            raise ValueError(f"Cannot read the {kind} favorites ({response}).")
        names = [n for n in known if isinstance(n, str)]
        for wanted in sorted(favorites):
            found = favorites_tool.match(names, wanted)
            if found is None:
                raise ValueError(f"No {kind} favorite named {wanted!r}.")
            exact[wanted] = found
    items = []
    for index, opening in enumerate(openings):
        row = by_guid[opening.wall_guid]
        label = f"{kind} {index} (wall {opening.wall_guid})"
        favorite = exact.get(opening.favorite_name or "")
        if row.get("type") != "Wall":
            raise ValueError(f"{label}: the owner is a {row.get('type')}, not a wall.")
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        if details.get("geometryType") != "Straight":
            raise ValueError(f"{label}: only straight walls are supported.")
        begin, end = details.get("begCoordinate"), details.get("endCoordinate")
        if not (isinstance(begin, dict) and isinstance(end, dict)):
            raise ValueError(f"{label}: the wall has no reference line coordinates.")
        length = math.hypot(end["x"] - begin["x"], end["y"] - begin["y"])
        if opening.center_offset > length + 1e-6:
            raise ValueError(
                f"{label}: center_offset {opening.center_offset} m is past the wall end "
                f"({length:.3f} m long)."
            )
        items.append(
            {
                "index": index,
                "status": "ready",
                "wall_guid": opening.wall_guid,
                "wall_length": length,
                "floorIndex": row.get("floorIndex"),
                "layerIndex": row.get("layerIndex"),
                "library_part": favorite or f"{kind} tool default",
                "parameters": _payload(opening) | ({"favoriteName": favorite} if favorite else {}),
            }
        )
    return {"operation": operation, "target": target, "items": items}


def _mismatches(kind: str):
    def check(item: dict, row: Any) -> list[str]:
        p = item["parameters"]
        details = {
            "ownerElementId": {"guid": item["wall_guid"]},
            "ownerElementType": "Wall",
            "centerOffset": p["centerOffset"],
        }
        for key in ("sillHeight", "width", "height"):
            if key in p:
                details[key] = p[key]
        expected = {"type": kind, "floorIndex": item["floorIndex"], "details": details}
        actual = row
        if isinstance(row, dict) and isinstance(row.get("details"), dict):
            # Tapir prints GUIDs in its own case; compare them as GUIDs.
            owner = row["details"].get("ownerElementId")
            if isinstance(owner, dict) and isinstance(owner.get("guid"), str):
                actual = {
                    **row,
                    "details": {
                        **row["details"],
                        "ownerElementId": {"guid": owner["guid"].upper()},
                    },
                }
            part = row["details"].get("libPart")
            if isinstance(part, dict) and isinstance(part.get("name"), str):
                item["library_part_name"] = part["name"]
        differences = write._mismatches(expected, actual)
        if "library_part_name" not in item:
            differences.append("details.libPart.name")
        return differences

    return check


async def _dispatch(client, receipt):
    await write._dispatch(client, receipt, _mismatches(KINDS[receipt["operation"]]))


async def _create(client, openings, port, dry_run, confirmation_token, operation):
    if not 1 <= len(openings) <= MAX_OPENINGS:
        raise ValueError(f"Pass between 1 and {MAX_OPENINGS} {KINDS[operation].lower()}s.")
    validated = [
        o if isinstance(o, OpeningCreate) else OpeningCreate.model_validate(o) for o in openings
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        operation,
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )


async def create_windows(
    client: ArchicadClient,
    windows: list[dict | OpeningCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 windows in existing straight walls. Metres.

    center_offset runs along the wall's reference line from its start. Size and sill
    are optional; the Window tool default or favorite_name decides the library part.
    """
    return await _create(client, windows, port, dry_run, confirmation_token, "create_windows")


async def create_doors(
    client: ArchicadClient,
    doors: list[dict | OpeningCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 doors in existing straight walls. Metres.

    center_offset runs along the wall's reference line from its start. Size and sill
    are optional; the Door tool default or favorite_name decides the library part.
    """
    return await _create(client, doors, port, dry_run, confirmation_token, "create_doors")
