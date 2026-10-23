"""Create new complex profiles from existing profile geometry (Tapir 1.7.0)."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import drafting, write

MAX_ITEMS = 20
Name = Annotated[str, Field(min_length=1, max_length=255)]


class ProfileCreate(write.InputModel):
    name: Name
    source_profile: Name
    walls: bool | None = None
    beams: bool | None = None
    columns: bool | None = None
    handrails: bool | None = None
    objects: bool | None = None

    @field_validator("name", "source_profile")
    @classmethod
    def trimmed(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("profile names must not have outer whitespace")
        return value


async def _plan(client, entries, port, operation):
    port, target, _ = await write._context(client, port)
    catalog = await drafting._attributes(client, port, "Profile")
    existing = {row["name"].casefold() for row in catalog}
    seen = set()
    items = []
    mapping = {
        "walls": "wallType",
        "beams": "beamType",
        "columns": "coluType",
        "handrails": "handrailType",
        "objects": "otherGDLObjectType",
    }
    for index, entry in enumerate(entries):
        key = entry.name.casefold()
        if key in existing:
            raise ValueError(f"Profile {entry.name!r} already exists; nothing is overwritten.")
        if key in seen:
            raise ValueError(f"Profile {entry.name!r} appears twice.")
        sources = [r for r in catalog if r["name"].casefold() == entry.source_profile.casefold()]
        if len(sources) != 1:
            problem = "is ambiguous" if sources else "does not exist"
            raise ValueError(f"Source profile {entry.source_profile!r} {problem}.")
        seen.add(key)
        payload = {
            "name": entry.name,
            "sourceAttributeId": {"attributeId": sources[0]["attributeId"]},
        }
        for field, native in mapping.items():
            value = getattr(entry, field)
            if value is not None:
                payload[native] = value
        items.append(
            {
                "index": index,
                "status": "ready",
                "source_name": sources[0]["name"],
                "source_guid": sources[0]["attributeId"]["guid"],
                "parameters": payload,
            }
        )
    return {"operation": operation, "target": target, "items": items}


async def _dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    try:
        raw = await client.tapir(
            port,
            "CreateProfiles",
            {"profileDataArray": [i["parameters"] for i in items], "overwriteExisting": False},
            timeout=timeout,
        )
    except ArchicadError as exc:
        for item in items:
            item.update(status="unknown", error=str(exc))
        return
    rows = raw.get("attributeIds")
    if not isinstance(rows, list) or len(rows) != len(items):
        for item in items:
            item.update(status="unknown", error="Unexpected response cardinality.")
        return
    created = []
    for item, row in zip(items, rows, strict=True):
        identifier = row.get("attributeId") if isinstance(row, dict) else None
        try:
            guid = str(UUID(identifier["guid"])).upper()
        except (TypeError, KeyError, ValueError):
            if isinstance(row, dict) and "error" in row:
                item.update(status="failed", error=row["error"])
            else:
                item.update(status="unknown", error="Missing profile ID or error.")
        else:
            item.update(status="unverified", profile_guid=guid)
            created.append(item)
    if not created:
        return
    try:
        response = await client.tapir(
            port,
            "GetProfiles",
            {
                "attributeIds": [
                    {"attributeId": {"guid": item["profile_guid"]}} for item in created
                ],
                "fields": [
                    "wallType",
                    "beamType",
                    "coluType",
                    "handrailType",
                    "otherGDLObjectType",
                ],
            },
            timeout=timeout,
        )
        after = response.get("profiles")
        if not isinstance(after, list) or len(after) != len(created):
            raise ValueError("Unexpected profile verification cardinality.")
        for item, row in zip(created, after, strict=True):
            item["after"] = row
            differences = write._mismatches(
                {k: v for k, v in item["parameters"].items() if k != "sourceAttributeId"}, row
            )
            item["status"] = "verification_failed" if differences else "verified"
            if differences:
                item["mismatches"] = differences
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)


async def create_profiles(
    client: ArchicadClient,
    profiles: list[dict | ProfileCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/create up to 20 profiles by copying existing complex geometry."""
    if not 1 <= len(profiles) <= MAX_ITEMS:
        raise ValueError(f"Pass between 1 and {MAX_ITEMS} profiles.")
    entries = [
        p if isinstance(p, ProfileCreate) else ProfileCreate.model_validate(p) for p in profiles
    ]
    return await write._write(
        client,
        entries,
        port,
        dry_run,
        confirmation_token,
        "create_profiles",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
