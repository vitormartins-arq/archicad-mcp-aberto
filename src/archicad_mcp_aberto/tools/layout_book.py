"""Layout Book subsets (Tapir 1.7.0 CreateLayoutSubset).

create_layout_subsets adds subsets (the folders of the Layout Book) at the top of the
book or inside an existing subset, with an optional own ID prefix and numbering style;
the rest comes from Archicad's subset defaults. A name already used by a subset under
the same parent is refused. The read-back finds each new subset in the Layout Book tree
under its parent. Never saves.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError, TapirError
from archicad_mcp_aberto.tools import documents, navigator, write

MAX_SUBSETS = 20
Text = Annotated[str, Field(min_length=1, max_length=255)]


class SubsetCreate(write.InputModel):
    name: Text
    parent: Text | None = None  # an existing subset by name or GUID; None for the top
    prefix: Annotated[str, Field(max_length=255)] | None = None
    numbering: Literal["abc", "ABC", "1", "01", "001", "0001", "noID"] | None = None

    @field_validator("name", "parent")
    @classmethod
    def trimmed(cls, value: str | None) -> str | None:
        return value if value is None else documents._trimmed(value)


async def _plan(client, subsets, port, operation):
    port, target, _ = await write._context(client, port)
    tree = await documents._tree(client, port, "LayoutBook")
    nodes = await navigator._view_tree(client, port, "LayoutBook")
    root = next((r for r in nodes if r["depth"] == 0), None)
    if root is None:
        raise ValueError("The Layout Book has no root item.")
    children: dict[str, set[str]] = {}
    for row in nodes:
        if row["type"] == "SubSetItem" and row["parent_guid"]:
            children.setdefault(row["parent_guid"], set()).add(row["name"].casefold())
    seen = set()
    items = []
    for index, subset in enumerate(subsets):
        label = f"Subset {index}"
        if subset.parent is None:
            parent_guid, parent_name = root["guid"], root["name"]
        else:
            parent = documents.subset_row(tree, subset.parent, label)
            parent_guid, parent_name = parent["navigator_guid"], parent["name"]
        key = (parent_guid, subset.name.casefold())
        if subset.name.casefold() in children.get(parent_guid, set()):
            raise ValueError(f"{label}: {parent_name!r} already has a subset {subset.name!r}.")
        if key in seen:
            raise ValueError(f"{label}: {subset.name!r} appears twice under {parent_name!r}.")
        seen.add(key)
        parameters: dict = {"name": subset.name}
        if subset.parent is not None:
            parameters["parentNavigatorItemId"] = {"guid": parent_guid}
        if subset.prefix is not None:
            parameters["ownPrefix"] = subset.prefix
        if subset.numbering is not None:
            parameters["numberingStyle"] = subset.numbering
        items.append(
            {
                "index": index,
                "status": "ready",
                "name": subset.name,
                "parent_name": parent_name,
                "parent_guid": parent_guid,
                "parameters": parameters,
            }
        )
    return {"operation": operation, "target": target, "items": items}


async def _dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    try:
        raw = await client.tapir(
            port,
            "CreateLayoutSubset",
            {"subsetsData": [i["parameters"] for i in items]},
            timeout=timeout,
        )
    except (TapirError, ArchicadError) as exc:
        for item in items:
            item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Outcome is unknown. Inspect Archicad; do not retry this plan."
        return
    receipt["raw_response"] = raw
    rows = raw.get("navigatorItems")
    if not isinstance(rows, list) or len(rows) != len(items):
        for item in items:
            item.update(status="unknown", error="Unexpected response cardinality.")
        return
    created = []
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        guid = documents._guid(row.get("navigatorItemId")) if isinstance(row, dict) else None
        if guid:
            item.update(status="unverified", navigator_guid=guid)
            created.append(item)
        elif isinstance(row, dict) and "error" in row:
            # Tapir also reports a subset it made but could not find again as an error.
            item.update(status="unknown", error=row["error"])
        else:
            item.update(status="unknown", error="Missing ID or error; inspect Archicad.")
    if not created:
        return
    try:
        nodes = {
            r["guid"]: r for r in await navigator._view_tree(client, port, "LayoutBook", timeout)
        }
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    for item in created:
        row = nodes.get(item["navigator_guid"])
        item["after"] = row
        problems = ["missing"] if row is None else [
            label for label, ok in (
                ("type", row["type"] == "SubSetItem"),
                ("name", row["name"] == item["name"]),
                ("parent", row["parent_guid"] == item["parent_guid"]),
            ) if not ok
        ]  # fmt: skip
        item["status"] = "verification_failed" if problems else "verified"
        if problems:
            item["mismatches"] = problems


async def create_layout_subsets(
    client: ArchicadClient,
    subsets: list[dict | SubsetCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 Layout Book subsets (name, parent subset, prefix,
    numbering)."""
    if not 1 <= len(subsets) <= MAX_SUBSETS:
        raise ValueError(f"Pass between 1 and {MAX_SUBSETS} subsets.")
    validated = [
        s if isinstance(s, SubsetCreate) else SubsetCreate.model_validate(s) for s in subsets
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_layout_subsets",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
