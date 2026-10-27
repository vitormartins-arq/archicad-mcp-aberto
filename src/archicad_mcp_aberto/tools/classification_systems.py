"""New classification systems with their item trees (Tapir 1.7.0 CreateClassificationSystems).

create_classification_systems adds a system (name, version, description, source, date)
with a tree of items (id, name, description, children) in one native call per batch. In
the Tapir 1.7.0 source a system sent without items gets no execution result, so at least
one item is required; an error in a child item is not reported, so the read-back compares
the whole tree. A name and version already used by a system is refused. The response
has no GUIDs: the new system is found by name and version in GetAllClassificationSystems.
Never saves.
"""

from __future__ import annotations

import datetime
from typing import Annotated

from pydantic import Field, field_validator, model_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import classifications, solids, write

MAX_SYSTEMS = 10
MAX_ITEMS = 500
MAX_DEPTH = 8
Text = Annotated[str, Field(min_length=1, max_length=255)]
Note = Annotated[str, Field(max_length=1000)]


def _visible(value: str) -> str:
    if not value.strip() or value != value.strip():
        raise ValueError("must be visible and have no outer whitespace.")
    return value


class SystemItem(write.InputModel):
    id: Text
    name: Text
    description: Note = ""
    children: Annotated[list[SystemItem], Field(max_length=MAX_ITEMS)] = []

    @field_validator("id", "name")
    @classmethod
    def visible(cls, value: str) -> str:
        return _visible(value)


class SystemCreate(write.InputModel):
    name: Text
    version: Text
    description: Note = ""
    source: Note = ""
    date: Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$")] | None = None  # today if None
    items: Annotated[list[SystemItem], Field(min_length=1, max_length=MAX_ITEMS)]

    @field_validator("name", "version")
    @classmethod
    def visible(cls, value: str) -> str:
        return _visible(value)

    @field_validator("date")
    @classmethod
    def real_date(cls, value: str | None) -> str | None:
        if value is not None:
            datetime.date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def sound_tree(self) -> SystemCreate:
        ids: list[str] = []

        def walk(rows: list[SystemItem], depth: int) -> None:
            if depth > MAX_DEPTH:
                raise ValueError(f"Items nest deeper than {MAX_DEPTH} levels.")
            for row in rows:
                ids.append(row.id.casefold())
                walk(row.children, depth + 1)

        walk(self.items, 1)
        if len(ids) > MAX_ITEMS:
            raise ValueError(f"A system takes at most {MAX_ITEMS} items.")
        if len(set(ids)) != len(ids):
            raise ValueError("An item ID appears twice in the system.")
        return self


def _details(rows: list[SystemItem]) -> list[dict]:
    out = []
    for row in rows:
        data: dict = {"id": row.id, "name": row.name, "description": row.description}
        if row.children:
            data["children"] = _details(row.children)
        out.append(data)
    return out


def _shape(rows: list[dict], parent: int | None = None, out: list | None = None) -> list:
    """The tree as (id, name, description, parent position) in depth-first order."""
    out = [] if out is None else out
    for row in rows:
        position = len(out)
        out.append((row["id"], row["name"], row["description"], parent))
        _shape(row.get("children", []), position, out)
    return out


def _tree_shape(rows: list[dict]) -> list:
    """The same for a read-back tree from classifications._creation_tree."""
    positions = {}
    out = []
    for row in rows:
        positions[row["guid"]] = len(out)
        parent = positions.get(row["parent_guid"]) if row["parent_guid"] else None
        out.append((row["id"], row["name"], row["description"], parent))
    return out


def _same_system(row: dict, data: dict) -> bool:
    return (
        str(row.get("name", "")).casefold() == data["name"].casefold()
        and str(row.get("version", "")).casefold() == data["version"].casefold()
    )


async def _plan(client, systems, port, operation):
    port, target, _ = await write._context(client, port)
    existing = await classifications._systems(client, port)
    items = []
    for index, system in enumerate(systems):
        data = {
            "name": system.name,
            "description": system.description,
            "source": system.source,
            "version": system.version,
            "date": system.date or datetime.date.today().isoformat(),
        }
        if any(_same_system(row, data) for row in existing):
            raise ValueError(
                f"System {index}: {system.name!r} version {system.version!r} already exists."
            )
        if any(_same_system(i["parameters"]["classificationSystem"], data) for i in items):
            raise ValueError(f"System {index}: the same name and version appear twice.")
        tree = _details(system.items)
        items.append(
            {
                "index": index,
                "status": "ready",
                "name": system.name,
                "version": system.version,
                "item_count": len(_shape(tree)),
                "parameters": {"classificationSystem": data, "classificationItems": tree},
            }
        )
    return {
        "operation": operation,
        "target": target,
        "existing_system_guids": sorted(row["guid"] for row in existing),
        "items": items,
    }


async def _dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    raw = await solids._results(
        client, port, "CreateClassificationSystems",
        {"classificationSystemsWithItems": [i["parameters"] for i in items]}, timeout,
    )  # fmt: skip
    if isinstance(raw, dict) and raw.get("success") is False:
        for item in items:
            item.update(status="failed", error=raw["error"])
        return
    rows = raw.get("executionResults") if isinstance(raw, dict) else None
    if not isinstance(rows, list) or len(rows) != len(items):
        return solids._unknown(receipt, raw if isinstance(raw, str) else "Unexpected response.")
    receipt["raw_response"] = raw
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        if isinstance(row, dict) and row.get("success") is True:
            item["status"] = "unverified"
        else:
            # A failure after the system was made leaves the system; the read-back says.
            item.update(
                status="failed", error=row.get("error", row) if isinstance(row, dict) else row
            )
    try:
        after = await classifications._systems(client, port)
        known = set(receipt["existing_system_guids"])
        for item in items:
            data = item["parameters"]["classificationSystem"]
            new = [r for r in after if r["guid"] not in known and _same_system(r, data)]
            if len(new) != 1:
                if item["status"] == "unverified":
                    item.update(status="verification_failed", mismatches=["system"])
                continue
            item["system_guid"] = new[0]["guid"]
            item["after"] = new[0]
            if item["status"] != "unverified":
                item["note"] = "The system was created; inspect or delete it in Archicad."
                continue
            tree = await classifications._creation_tree(client, port, new[0]["guid"], timeout)
            problems = [
                key
                for key in ("description", "source", "date")
                if new[0].get(key) != item["parameters"]["classificationSystem"][key]
            ]
            if _tree_shape(tree) != _shape(item["parameters"]["classificationItems"]):
                problems.append("items")
            item["status"] = "verification_failed" if problems else "verified"
            if problems:
                item["mismatches"] = problems
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)


async def create_classification_systems(
    client: ArchicadClient,
    systems: list[dict | SystemCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 10 new classification systems, each with a tree of up to 500
    items (id, name, description, children)."""
    if not 1 <= len(systems) <= MAX_SYSTEMS:
        raise ValueError(f"Pass between 1 and {MAX_SYSTEMS} systems.")
    validated = [
        s if isinstance(s, SystemCreate) else SystemCreate.model_validate(s) for s in systems
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_classification_systems",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
