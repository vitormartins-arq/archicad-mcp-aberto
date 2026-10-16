"""Read-only Design Options access from Tapir 1.7.0.

The native availability differs by command: combinations require Archicad 27+, while
sets, option details and element membership require Archicad 29+. Nothing here writes.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port
from archicad_mcp_aberto.tools import read

MAX_GUIDS = 500


def _guid(value: Any, label: str) -> str:
    value = value.get("guid") if isinstance(value, dict) else value
    try:
        guid = UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f"Unexpected {label} GUID.") from None
    if not guid.int:
        raise ValueError(f"Unexpected null {label} GUID.")
    return str(guid).upper()


def _input_guids(values: list[str], label: str) -> list[str]:
    if not isinstance(values, list) or not 1 <= len(values) <= MAX_GUIDS:
        raise ValueError(f"{label} must contain 1 to {MAX_GUIDS} GUIDs.")
    guids = [_guid(value, label) for value in values]
    if len(set(guids)) != len(guids):
        raise ValueError(f"{label} must not contain duplicate GUIDs.")
    return guids


def _id_list(value: Any, key: str, label: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"Unexpected {label} list.")
    return [_guid(row.get(key) if isinstance(row, dict) else None, label) for row in value]


async def list_design_options(
    client: ArchicadClient,
    port: int | None = None,
    query: str | None = None,
    offset: int = 0,
    limit: int = 200,
) -> dict:
    """List option sets, options and combinations; filter options after validation."""
    read.page_args(offset, limit, 500)
    port = await resolve_port(client, port)
    sets_raw = await client.tapir(port, "GetDesignOptionSets")
    options_raw = await client.tapir(port, "GetDesignOptions")
    combinations_raw = await client.tapir(port, "GetDesignOptionCombinations")

    options = options_raw.get("designOptions")
    sets = sets_raw.get("designOptionSets")
    combinations = combinations_raw.get("designOptionCombinations")
    if (
        not isinstance(options, list)
        or not isinstance(sets, list)
        or not isinstance(combinations, list)
    ):
        raise ValueError("Unexpected Design Options inventory response.")

    normalized_options = []
    for row in options:
        if not isinstance(row, dict) or not all(
            isinstance(row.get(k), str) for k in ("name", "id", "ownerSetName")
        ):
            raise ValueError("Unexpected design option details.")
        normalized_options.append(
            {
                "guid": _guid(row.get("designOptionId"), "design option"),
                "id": row["id"],
                "name": row["name"],
                "owner_set_name": row["ownerSetName"],
            }
        )

    normalized_sets = []
    for row in sets:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise ValueError("Unexpected design option set details.")
        normalized_sets.append(
            {
                "guid": _guid(row.get("designOptionSetId"), "design option set"),
                "name": row["name"],
                "design_option_guids": _id_list(
                    row.get("designOptions"), "designOptionId", "design option"
                ),
            }
        )

    normalized_combinations = []
    for row in combinations:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            raise ValueError("Unexpected design option combination details.")
        item = {
            "guid": _guid(row.get("designOptionCombinationId"), "design option combination"),
            "name": row["name"],
        }
        if "activeDesignOptions" in row:
            item["active_design_option_guids"] = _id_list(
                row["activeDesignOptions"], "designOptionId", "active design option"
            )
        normalized_combinations.append(item)

    if query:
        text = query.casefold()
        normalized_options = [
            row
            for row in normalized_options
            if any(text in row[key].casefold() for key in ("id", "name", "owner_set_name"))
        ]
    return {
        "port": port,
        "sets": normalized_sets,
        "combinations": normalized_combinations,
        "options": normalized_options[offset : offset + limit],
        "total_options": len(normalized_options),
        "offset": offset,
        "limit": limit,
    }


async def get_elements_of_design_options(
    client: ArchicadClient, design_option_guids: list[str], port: int | None = None
) -> dict:
    """Return element GUIDs or the native per-option error for 1–500 options."""
    guids = _input_guids(design_option_guids, "design_option_guids")
    port = await resolve_port(client, port)
    raw = await client.tapir(
        port,
        "GetElementsOfDesignOptions",
        {"designOptions": [{"designOptionId": {"guid": guid}} for guid in guids]},
    )
    rows = raw.get("elementsOfDesignOptions")
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected design option elements response.")
    out = []
    for requested, row in zip(guids, rows, strict=True):
        if not isinstance(row, dict):
            raise ValueError("Unexpected design option elements item.")
        if "error" in row:
            out.append({"design_option_guid": requested, "error": row["error"]})
            continue
        returned = _guid(row.get("designOptionId"), "design option")
        if returned != requested:
            raise ValueError("Design option response order or identity changed.")
        out.append(
            {
                "design_option_guid": returned,
                "element_guids": _id_list(row.get("elements"), "elementId", "element"),
            }
        )
    return {"port": port, "items": out}


async def get_design_options_for_elements(
    client: ArchicadClient, element_guids: list[str], port: int | None = None
) -> dict:
    """Return the native Design Option status for 1–500 elements, preserving order."""
    guids = _input_guids(element_guids, "element_guids")
    port = await resolve_port(client, port)
    raw = await client.tapir(
        port, "GetDesignOptionForElements", {"elements": read.element_ids(guids)}
    )
    rows = raw.get("designOptionForElements")
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected element Design Option response.")
    out = []
    allowed = {
        "NotExistingElement",
        "MissingDesignOption",
        "NotLinkedToAnyDesignOption",
        "LinkedToDesignOption",
    }
    for requested, row in zip(guids, rows, strict=True):
        if not isinstance(row, dict) or row.get("type") not in allowed:
            raise ValueError("Unexpected element Design Option status.")
        returned = _guid(row.get("elementId"), "element")
        if returned != requested:
            raise ValueError("Element response order or identity changed.")
        item = {"element_guid": returned, "status": row["type"]}
        if row["type"] == "LinkedToDesignOption":
            option = row.get("designOption")
            if not isinstance(option, dict) or not all(
                isinstance(option.get(k), str) for k in ("name", "id", "ownerSetName")
            ):
                raise ValueError("Unexpected linked design option details.")
            item["design_option"] = {
                "guid": _guid(option.get("designOptionId"), "design option"),
                "id": option["id"],
                "name": option["name"],
                "owner_set_name": option["ownerSetName"],
            }
        out.append(item)
    return {"port": port, "items": out}
