"""Solid element operations and trims (Tapir 1.7.0).

create_solid_operations links an operator to a target (CreateSolidElementLinks):
subtraction, subtraction upwards or downwards, intersection or addition, as in Design >
Solid Element Operations. trim_to_roof trims construction elements with one roof or shell
(TrimElements with trimmingElement), as Design > Trim to Roof/Shell. Both need editable,
non-hotlinked elements, refuse a link or trim that already exists, and read the result
back (GetSolidElementLinks, GetElementTrims). remove_solid_operations and remove_trims
undo them (RemoveSolidElementLinks, RemoveElementTrims): each link or trim must exist, and
the read-back checks it is gone. Never saves.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError, TapirError
from archicad_mcp_aberto.tools import design_options, edit, read, write

MAX_LINKS = 50
MAX_TRIMMED = 100
Guid = Annotated[str, Field(min_length=36, max_length=36)]
Operation = Literal[
    "Subtraction", "SubtractionUpwards", "SubtractionDownwards", "Intersection", "Addition"
]
TRIMMERS = {"Roof", "Shell"}


def _guid(value: str) -> str:
    return design_options._guid(value, "element")


class SolidLink(write.InputModel):
    target_guid: Guid
    operator_guid: Guid
    operation: Operation = "Subtraction"
    inherit_operator_attributes: bool = False
    skip_polygon_holes: bool = False

    @field_validator("target_guid", "operator_guid")
    @classmethod
    def valid_guid(cls, value: str) -> str:
        return _guid(value)

    @model_validator(mode="after")
    def two_elements(self) -> SolidLink:
        if self.target_guid == self.operator_guid:
            raise ValueError("An element cannot operate on itself.")
        return self


class LinkPair(write.InputModel):
    target_guid: Guid
    operator_guid: Guid

    @field_validator("target_guid", "operator_guid")
    @classmethod
    def valid_guid(cls, value: str) -> str:
        return _guid(value)


class Trim(write.InputModel):
    element_guids: Annotated[list[Guid], Field(min_length=1, max_length=MAX_TRIMMED)]
    roof_guid: Guid
    keep: Literal["KeepInside", "KeepOutside", "KeepAll"] = "KeepInside"

    @field_validator("element_guids")
    @classmethod
    def valid_guids(cls, value: list[str]) -> list[str]:
        guids = [_guid(v) for v in value]
        if len(set(guids)) != len(guids):
            raise ValueError("An element appears twice.")
        return guids

    @field_validator("roof_guid")
    @classmethod
    def valid_roof(cls, value: str) -> str:
        return _guid(value)

    @model_validator(mode="after")
    def roof_not_trimmed(self) -> Trim:
        if self.roof_guid in self.element_guids:
            raise ValueError("The roof or shell cannot trim itself.")
        return self


async def _links(client, port, guids, timeout=None) -> dict[str, list[dict]]:
    """Target GUID -> its links (operator, operation, flags)."""
    extra = {} if timeout is None else {"timeout": timeout}
    response = await client.tapir(
        port, "GetSolidElementLinks", {"elements": read.element_ids(guids)}, **extra
    )
    rows = response.get("solidLinks")
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected solid element links response.")
    out = {}
    for guid, row in zip(guids, rows, strict=True):
        links = row.get("solidLinksWithTheGivenTarget") if isinstance(row, dict) else None
        if not isinstance(links, list):
            raise ValueError(f"Cannot read the solid links of {guid}.")
        out[guid] = links
    return out


def _operator(link: dict) -> str | None:
    value = link.get("operatorId") if isinstance(link, dict) else None
    guid = value.get("guid") if isinstance(value, dict) else None
    return guid.upper() if isinstance(guid, str) else None


async def _link_plan(client, links, port, operation):
    guids = list(dict.fromkeys(g for link in links for g in (link.target_guid, link.operator_guid)))
    port, target, rows = await edit._editable(client, guids, port)
    types = {g: r.get("type") for g, r in zip(guids, rows, strict=True)}
    targets = list(dict.fromkeys(link.target_guid for link in links))
    existing = await _links(client, port, targets)
    seen = set()
    items = []
    for index, link in enumerate(links):
        pair = (link.target_guid, link.operator_guid)
        if pair in seen or (pair[::-1] in seen):
            raise ValueError(f"Link {index}: the same two elements appear twice.")
        seen.add(pair)
        if any(_operator(x) == link.operator_guid for x in existing[link.target_guid]):
            raise ValueError(f"Link {index}: this operator already acts on the target.")
        items.append(
            {
                "index": index,
                "status": "ready",
                "target_type": types[link.target_guid],
                "operator_type": types[link.operator_guid],
                "parameters": {
                    "targetId": {"guid": link.target_guid},
                    "operatorId": {"guid": link.operator_guid},
                    "operation": link.operation,
                    "linkFlags": {
                        "inheritOperatorAttributes": link.inherit_operator_attributes,
                        "skipPolygonHoles": link.skip_polygon_holes,
                    },
                },
            }
        )
    return {"operation": operation, "target": target, "items": items}


async def _results(client, port, command, payload, timeout) -> dict | str:
    try:
        return await client.tapir(port, command, payload, timeout=timeout)
    except TapirError as exc:
        # Tapir answered with an error: nothing was done, the outcome is known.
        return {"success": False, "error": exc.detail} if exc.detail else f"{command}: {exc}"
    except ArchicadError as exc:
        return f"{command}: {exc}"


def _unknown(receipt: dict, error: str) -> None:
    for item in receipt["items"]:
        item.update(status="unknown", error=error)
    receipt["warning"] = "Outcome is unknown. Inspect Archicad; do not retry this plan."


async def _link_dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    raw = await _results(
        client, port, "CreateSolidElementLinks",
        {"solidLinks": [i["parameters"] for i in items]}, timeout,
    )  # fmt: skip
    if isinstance(raw, dict) and raw.get("success") is False:
        for item in items:
            item.update(status="failed", error=raw["error"])
        return
    rows = raw.get("executionResults") if isinstance(raw, dict) else None
    if not isinstance(rows, list) or len(rows) != len(items):
        return _unknown(receipt, raw if isinstance(raw, str) else "Unexpected response.")
    receipt["raw_response"] = raw
    linked = []
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        if isinstance(row, dict) and row.get("success") is True:
            item["status"] = "unverified"
            linked.append(item)
        else:
            item.update(
                status="failed", error=row.get("error", row) if isinstance(row, dict) else row
            )
    if not linked:
        return
    targets = list(dict.fromkeys(i["parameters"]["targetId"]["guid"] for i in linked))
    try:
        after = await _links(client, port, targets, timeout)
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    for item in linked:
        p = item["parameters"]
        found = [x for x in after[p["targetId"]["guid"]] if _operator(x) == p["operatorId"]["guid"]]
        item["after"] = found[0] if found else None
        problems = ["missing"] if not found else [
            k for k in ("operation", "linkFlags") if found[0].get(k) != p[k]]  # fmt: skip
        item["status"] = "verification_failed" if problems else "verified"
        if problems:
            item["mismatches"] = problems


async def create_solid_operations(
    client: ArchicadClient,
    links: list[dict | SolidLink],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 50 solid element operation links (target, operator,
    operation, flags) between existing editable elements."""
    if not 1 <= len(links) <= MAX_LINKS:
        raise ValueError(f"Pass between 1 and {MAX_LINKS} links.")
    validated = [x if isinstance(x, SolidLink) else SolidLink.model_validate(x) for x in links]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_solid_operations",
        planner_override=_link_plan,
        dispatcher_override=_link_dispatch,
    )


async def _trims(client, port, guids, timeout=None) -> dict[str, list[dict]]:
    """Element GUID -> the roofs and shells trimming it, with the trim type."""
    extra = {} if timeout is None else {"timeout": timeout}
    response = await client.tapir(
        port, "GetElementTrims", {"elements": read.element_ids(guids)}, **extra
    )
    rows = response.get("elementTrims")
    if not isinstance(rows, list) or len(rows) != len(guids):
        raise ValueError("Unexpected element trims response.")
    out = {}
    for guid, row in zip(guids, rows, strict=True):
        trimmed_by = row.get("trimmedBy") if isinstance(row, dict) else None
        if not isinstance(trimmed_by, list):
            raise ValueError(f"Cannot read the trims of {guid} ({row}).")
        out[guid] = trimmed_by
    return out


def _trimmer(entry: dict) -> str | None:
    value = entry.get("elementId") if isinstance(entry, dict) else None
    guid = value.get("guid") if isinstance(value, dict) else None
    return guid.upper() if isinstance(guid, str) else None


async def _trim_plan(client, trims, port, operation):
    (trim,) = trims
    guids = [*trim.element_guids, trim.roof_guid]
    port, target, rows = await edit._editable(client, guids, port)
    types = {g: r.get("type") for g, r in zip(guids, rows, strict=True)}
    if types[trim.roof_guid] not in TRIMMERS:
        raise ValueError(
            f"Element {trim.roof_guid} is a {types[trim.roof_guid]}, not a roof or shell."
        )
    current = await _trims(client, port, trim.element_guids)
    items = []
    for index, guid in enumerate(trim.element_guids):
        if any(_trimmer(e) == trim.roof_guid for e in current[guid]):
            raise ValueError(f"Element {guid} is already trimmed by this roof or shell.")
        items.append({"index": index, "status": "ready", "element_guid": guid, "type": types[guid]})
    return {
        "operation": operation,
        "target": target,
        "roof_guid": trim.roof_guid,
        "roof_type": types[trim.roof_guid],
        "keep": trim.keep,
        "items": items,
    }


async def _trim_dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    raw = await _results(
        client, port, "TrimElements",
        {"elements": read.element_ids([i["element_guid"] for i in items]),
         "trimmingElement": {"guid": receipt["roof_guid"]}, "trimType": receipt["keep"]},
        timeout,
    )  # fmt: skip
    if not isinstance(raw, dict) or not isinstance(raw.get("success"), bool):
        return _unknown(receipt, raw if isinstance(raw, str) else "Unexpected response.")
    receipt["raw_response"] = raw
    if not raw["success"]:
        for item in items:
            item.update(status="failed", error=raw.get("error", raw))
        return
    try:
        after = await _trims(client, port, [i["element_guid"] for i in items], timeout)
    except (ArchicadError, ValueError) as exc:
        for item in items:
            item["status"] = "unverified"
        receipt["verification_error"] = str(exc)
        return
    for item in items:
        found = [e for e in after[item["element_guid"]] if _trimmer(e) == receipt["roof_guid"]]
        item["after"] = found[0] if found else None
        problems = ["missing"] if not found else (
            [] if found[0].get("trimType") == receipt["keep"] else ["trimType"])  # fmt: skip
        item["status"] = "verification_failed" if problems else "verified"
        if problems:
            item["mismatches"] = problems


async def trim_to_roof(
    client: ArchicadClient,
    element_guids: list[str],
    roof_guid: str,
    keep: str = "KeepInside",
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply trimming up to 100 editable elements with one roof or shell."""
    trim = Trim.model_validate(
        {"element_guids": element_guids, "roof_guid": roof_guid, "keep": keep}
    )
    return await write._write(
        client,
        [trim],
        port,
        dry_run,
        confirmation_token,
        "trim_to_roof",
        planner_override=_trim_plan,
        dispatcher_override=_trim_dispatch,
    )


def _pair_results(receipt: dict, raw) -> list[dict] | None:
    """Mark each item by its execution result; return the ones to read back."""
    items = receipt["items"]
    rows = raw.get("executionResults") if isinstance(raw, dict) else None
    if not isinstance(rows, list) or len(rows) != len(items):
        _unknown(receipt, raw if isinstance(raw, str) else "Unexpected response.")
        return None
    receipt["raw_response"] = raw
    done = []
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        if isinstance(row, dict) and row.get("success") is True:
            item["status"] = "unverified"
            done.append(item)
        else:
            item.update(
                status="failed", error=row.get("error", row) if isinstance(row, dict) else row
            )
    return done


async def _unlink_plan(client, links, port, operation):
    guids = list(dict.fromkeys(g for link in links for g in (link.target_guid, link.operator_guid)))
    port, target, rows = await edit._editable(client, guids, port)
    types = {g: r.get("type") for g, r in zip(guids, rows, strict=True)}
    existing = await _links(client, port, list(dict.fromkeys(x.target_guid for x in links)))
    seen = set()
    items = []
    for index, link in enumerate(links):
        pair = (link.target_guid, link.operator_guid)
        if pair in seen:
            raise ValueError(f"Link {index}: the same link appears twice.")
        seen.add(pair)
        found = [x for x in existing[link.target_guid] if _operator(x) == link.operator_guid]
        if not found:
            raise ValueError(f"Link {index}: this operator does not act on the target.")
        items.append(
            {
                "index": index,
                "status": "ready",
                "target_type": types[link.target_guid],
                "operator_type": types[link.operator_guid],
                "before": found[0],
                "parameters": {
                    "targetId": {"guid": link.target_guid},
                    "operatorId": {"guid": link.operator_guid},
                },
            }
        )
    return {"operation": operation, "target": target, "items": items}


async def _unlink_dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    raw = await _results(
        client, port, "RemoveSolidElementLinks",
        {"solidLinks": [i["parameters"] for i in items]}, timeout,
    )  # fmt: skip
    removed = _pair_results(receipt, raw)
    if not removed:
        return
    targets = list(dict.fromkeys(i["parameters"]["targetId"]["guid"] for i in removed))
    try:
        after = await _links(client, port, targets, timeout)
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    for item in removed:
        p = item["parameters"]
        left = any(_operator(x) == p["operatorId"]["guid"] for x in after[p["targetId"]["guid"]])
        item["status"] = "verification_failed" if left else "verified"
        if left:
            item["mismatches"] = ["still linked"]


async def remove_solid_operations(
    client: ArchicadClient,
    links: list[dict | LinkPair],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply removing up to 50 existing solid element operation links (target,
    operator) between editable elements. The elements stay."""
    if not 1 <= len(links) <= MAX_LINKS:
        raise ValueError(f"Pass between 1 and {MAX_LINKS} links.")
    validated = [x if isinstance(x, LinkPair) else LinkPair.model_validate(x) for x in links]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "remove_solid_operations",
        planner_override=_unlink_plan,
        dispatcher_override=_unlink_dispatch,
    )


async def _untrim_plan(client, trims, port, operation):
    (trim,) = trims
    guids = [*trim.element_guids, trim.roof_guid]
    port, target, rows = await edit._editable(client, guids, port)
    types = {g: r.get("type") for g, r in zip(guids, rows, strict=True)}
    current = await _trims(client, port, trim.element_guids)
    items = []
    for index, guid in enumerate(trim.element_guids):
        found = [e for e in current[guid] if _trimmer(e) == trim.roof_guid]
        if not found:
            raise ValueError(f"Element {guid} is not trimmed by {trim.roof_guid}.")
        items.append(
            {
                "index": index,
                "status": "ready",
                "element_guid": guid,
                "type": types[guid],
                "before": found[0],
                "parameters": {
                    "elementId": {"guid": guid},
                    "trimmingElementId": {"guid": trim.roof_guid},
                },
            }
        )
    return {
        "operation": operation,
        "target": target,
        "roof_guid": trim.roof_guid,
        "roof_type": types[trim.roof_guid],
        "items": items,
    }


async def _untrim_dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    raw = await _results(
        client, port, "RemoveElementTrims",
        {"elementPairs": [i["parameters"] for i in items]}, timeout,
    )  # fmt: skip
    removed = _pair_results(receipt, raw)
    if not removed:
        return
    try:
        after = await _trims(client, port, [i["element_guid"] for i in removed], timeout)
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    for item in removed:
        left = any(_trimmer(e) == receipt["roof_guid"] for e in after[item["element_guid"]])
        item["status"] = "verification_failed" if left else "verified"
        if left:
            item["mismatches"] = ["still trimmed"]


async def remove_trims(
    client: ArchicadClient,
    element_guids: list[str],
    roof_guid: str,
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply removing the trim of one roof or shell from up to 100 elements it
    trims. The elements stay."""
    trim = Trim.model_validate({"element_guids": element_guids, "roof_guid": roof_guid})
    return await write._write(
        client,
        [trim],
        port,
        dry_run,
        confirmation_token,
        "remove_trims",
        planner_override=_untrim_plan,
        dispatcher_override=_untrim_dispatch,
    )
