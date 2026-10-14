"""Custom property groups and properties (Options > Property Manager), via Tapir 1.7.0.

create_property_groups adds empty custom groups; create_properties adds custom
properties to an existing custom group, with an optional default value, enum options and
the classification items it is available for. Neither ever changes or deletes an
existing group or property: a name already in use is refused in the preview. Both use
the shared preview, single-use token and receipts, and read the result back with
GetAllProperties. Lengths are in meters and angles in radians. Never saves.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError, TapirError, resolve_port
from archicad_mcp_aberto.tools import classifications, write

MAX_GROUPS = 20
MAX_PROPERTIES = 50
MAX_AVAILABILITY = 2000
Name = Annotated[str, Field(min_length=1, max_length=255)]
Description = Annotated[str, Field(max_length=1000)]
PropertyType = Literal[
    "number",
    "integer",
    "string",
    "boolean",
    "length",
    "area",
    "volume",
    "angle",
    "numberList",
    "integerList",
    "stringList",
    "booleanList",
    "lengthList",
    "areaList",
    "volumeList",
    "angleList",
    "singleEnum",
    "multiEnum",
]
REAL = {"number", "length", "area", "volume", "angle"}
MEASURE = {"length": "Length", "area": "Area", "volume": "Volume", "angle": "Angle"}
ENUMS = {"singleEnum", "multiEnum"}


def _shape(kind: str) -> dict:
    """What GetAllProperties reports for a property created with this Tapir type."""
    if kind == "singleEnum":
        return {"collection": "SingleChoiceEnumeration", "value": "String", "measure": "Default"}
    if kind == "multiEnum":
        return {"collection": "MultipleChoiceEnumeration", "value": "String", "measure": "Default"}
    base = kind.removesuffix("List")
    value = {"integer": "Integer", "string": "String", "boolean": "Boolean"}.get(base, "Real")
    return {
        "collection": "List" if kind.endswith("List") else "Single",
        "value": value,
        "measure": MEASURE.get(base, "Default"),
    }


def _trimmed(value: str) -> str:
    if value != value.strip():
        raise ValueError("names must not start or end with spaces.")
    return value


def _scalar_ok(base: str, value: Any) -> bool:
    if base in REAL:
        return (
            isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)
        )
    if base == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    return isinstance(value, {"string": str, "boolean": bool}[base])


async def _catalog(client, port, timeout=None) -> tuple[list[dict], list[dict]]:
    extra = {} if timeout is None else {"timeout": timeout}
    response = await client.tapir(port, "GetAllProperties", **extra)
    groups, properties = response.get("propertyGroups"), response.get("properties")
    if not isinstance(groups, list) or not isinstance(properties, list):
        raise ValueError("Unexpected property catalog response.")
    return (
        [g for g in groups if isinstance(g, dict) and isinstance(g.get("name"), str)],
        [p for p in properties if isinstance(p, dict)],
    )


def _gid(row: dict, key: str) -> str | None:
    value = row.get(key)
    return classifications._guid(value.get("guid")) if isinstance(value, dict) else None


async def list_property_groups(client: ArchicadClient, port: int | None = None) -> dict:
    port = await resolve_port(client, port)
    groups, properties = await _catalog(client, port)
    counts: dict[str | None, int] = {}
    for prop in properties:
        key = _gid(prop, "propertyGroupId")
        counts[key] = counts.get(key, 0) + 1
    rows = [
        {
            "group_guid": _gid(g, "propertyGroupId"),
            "name": g["name"],
            "description": g.get("description", ""),
            "is_custom": g.get("isCustom") is True,
            "property_count": counts.get(_gid(g, "propertyGroupId"), 0),
        }
        for g in groups
    ]
    return {"port": port, "total": len(rows), "groups": rows}


class PropertyGroupCreate(write.InputModel):
    name: Name
    description: Description = ""

    @field_validator("name")
    @classmethod
    def trimmed(cls, value: str) -> str:
        return _trimmed(value)


class PropertyCreate(write.InputModel):
    name: Name
    group: Name
    type: PropertyType
    description: Description = ""
    editable: bool = True
    default: Any = None
    enum_values: Annotated[list[Name], Field(min_length=1, max_length=200)] | None = None
    available_for: Annotated[list[Name], Field(max_length=MAX_AVAILABILITY)] = []
    available_for_system: Name | None = None

    @field_validator("name")
    @classmethod
    def trimmed(cls, value: str) -> str:
        return _trimmed(value)

    @field_validator("available_for")
    @classmethod
    def canonical_items(cls, value: list[str]) -> list[str]:
        # A classification item GUID, or its id or name as Archicad shows it ("Parede").
        out = []
        for v in value:
            try:
                out.append(str(UUID(v)).upper())
            except ValueError:
                if not v.strip():
                    raise ValueError("available_for entries must not be blank.") from None
                out.append(v.strip())
        return out

    @model_validator(mode="after")
    def consistent(self):
        kind = self.type
        if kind in ENUMS:
            values = self.enum_values or []
            if not values:
                raise ValueError(f"{kind} needs enum_values.")
            if len({v.casefold() for v in values}) != len(values):
                raise ValueError("enum_values must be unique (case ignored).")
            if any(v != v.strip() for v in values):
                raise ValueError("enum_values must not start or end with spaces.")
        elif self.enum_values is not None:
            raise ValueError("enum_values are only for singleEnum and multiEnum.")
        default = self.default
        if default is None:
            return self
        if kind == "singleEnum":
            ok = isinstance(default, str) and default in (self.enum_values or [])
        elif kind == "multiEnum":
            ok = (
                isinstance(default, list)
                and bool(default)
                and len(set(map(str, default))) == len(default)
                and all(isinstance(d, str) and d in (self.enum_values or []) for d in default)
            )
        elif kind.endswith("List"):
            base = kind.removesuffix("List")
            ok = isinstance(default, list) and all(_scalar_ok(base, d) for d in default)
        else:
            ok = _scalar_ok(kind, default)
        if not ok:
            raise ValueError(f"default does not fit type {kind} (enum defaults must be options).")
        return self


def _default_payload(prop: PropertyCreate) -> dict:
    value = prop.default
    if prop.type == "singleEnum":
        value = {"type": "displayValue", "displayValue": value}
    elif prop.type == "multiEnum":
        value = [{"enumValueId": {"type": "displayValue", "displayValue": v}} for v in value]
    elif prop.type in REAL and isinstance(value, int):
        value = float(value)
    elif prop.type.removesuffix("List") in REAL and isinstance(value, list):
        value = [float(v) for v in value]
    return {"basicDefaultValue": {"type": prop.type, "status": "normal", "value": value}}


def _pick_group(groups: list[dict], wanted: str) -> dict:
    rows = [{**g, "guid": _gid(g, "propertyGroupId")} for g in groups]
    return classifications._pick(rows, wanted, ("name",), "Property group")


async def _group_plan(client, groups, port, operation):
    port, target, _ = await write._context(client, port)
    existing, _ = await _catalog(client, port)
    names = {g["name"].casefold() for g in existing}
    seen, items = set(), []
    for index, group in enumerate(groups):
        key = group.name.casefold()
        if key in names:
            raise ValueError(f"Property group {group.name!r} already exists; nothing is changed.")
        if key in seen:
            raise ValueError(f"Property group {group.name!r} appears twice.")
        seen.add(key)
        items.append(
            {
                "index": index,
                "status": "ready",
                "name": group.name,
                "parameters": {
                    "propertyGroup": {"name": group.name, "description": group.description}
                },
            }
        )
    return {"operation": operation, "target": target, "items": items}


async def _availability(client, port, props) -> dict[int, list[str]]:
    if not any(p.available_for or p.available_for_system for p in props):
        return {}
    systems = await classifications._systems(client, port)
    items = {s["guid"]: await classifications._items(client, port, s["guid"]) for s in systems}
    every = [row for rows in items.values() for row in rows]
    known = {row["guid"] for row in every}
    out = {}
    for index, prop in enumerate(props):
        chosen, missing = [], []
        for wanted in prop.available_for:
            if wanted in known:
                chosen.append(wanted)
                continue
            try:
                chosen.append(
                    classifications._pick(every, wanted, ("id", "name"), "Classification item")[
                        "guid"
                    ]
                )
            except ValueError as exc:
                if "ambiguous" in str(exc):
                    raise ValueError(f"Property {index}: {exc}") from None
                missing.append(wanted)
        if missing:
            raise ValueError(f"Property {index}: classification items not found: {missing}.")
        if prop.available_for_system:
            system = classifications._pick_system(systems, prop.available_for_system)
            chosen += [row["guid"] for row in items[system["guid"]]]
        out[index] = list(dict.fromkeys(chosen))
        if len(out[index]) > MAX_AVAILABILITY:
            raise ValueError(f"Property {index}: at most {MAX_AVAILABILITY} classification items.")
    return out


async def _property_plan(client, props, port, operation):
    port, target, _ = await write._context(client, port)
    groups, existing = await _catalog(client, port)
    availability = await _availability(client, port, props)
    taken = {
        (_gid(p, "propertyGroupId"), str(p.get("propertyName", "")).casefold()) for p in existing
    }
    seen, items = set(), []
    for index, prop in enumerate(props):
        try:
            group = _pick_group(groups, prop.group)
        except ValueError as exc:
            raise ValueError(f"Property {index}: {exc}") from None
        if group.get("isCustom") is not True:
            raise ValueError(
                f"Property {index}: group {group['name']!r} is built in; use a custom one."
            )
        key = (group["guid"], prop.name.casefold())
        if key in taken:
            raise ValueError(
                f"Property {prop.name!r} already exists in {group['name']!r}; nothing is changed."
            )
        if key in seen:
            raise ValueError(f"Property {prop.name!r} appears twice in {group['name']!r}.")
        seen.add(key)
        chosen = availability.get(index, [])
        definition: dict[str, Any] = {
            "name": prop.name,
            "description": prop.description,
            "type": prop.type,
            "isEditable": prop.editable,
            "availability": [{"classificationItemId": {"guid": g}} for g in chosen],
            "group": {"propertyGroupId": {"guid": group["guid"]}},
        }
        if prop.enum_values:
            definition["possibleEnumValues"] = [
                {"enumValue": {"displayValue": v}} for v in prop.enum_values
            ]
        if prop.default is not None:
            definition["defaultValue"] = _default_payload(prop)
        item = {
            "index": index,
            "status": "ready",
            "name": prop.name,
            "group_name": group["name"],
            "group_guid": group["guid"],
            "type": prop.type,
            "availability_count": len(chosen),
            "parameters": {"propertyDefinition": definition},
        }
        if not chosen:
            item["warning"] = (
                "Available for no classification: Archicad shows a custom property only on "
                "elements whose classification it is available for."
            )
        items.append(item)
    return {"operation": operation, "target": target, "items": items}


async def _create(client, receipt, command, list_key, answer_key, id_key):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    try:
        raw = await client.tapir(
            port, command, {list_key: [i["parameters"] for i in items]}, timeout=timeout
        )
    except TapirError as exc:
        status = "failed" if exc.detail else "unknown"
        for item in items:
            item.update(status=status, error=exc.detail or str(exc))
        if not exc.detail:
            receipt["warning"] = "Outcome is unknown. Inspect Archicad; do not retry this plan."
        return []
    except ArchicadError as exc:
        for item in items:
            item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Outcome is unknown. Inspect Archicad; do not retry this plan."
        return []
    receipt["raw_response"] = raw
    rows = raw.get(answer_key)
    if not isinstance(rows, list) or len(rows) != len(items):
        for item in items:
            item.update(status="unknown", error="Unexpected response cardinality.")
        return []
    created = []
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        guid = _gid(row, id_key) if isinstance(row, dict) else None
        if isinstance(row, dict) and "error" in row:
            item.update(status="failed", error=row["error"])
        elif guid:
            item.update(status="unverified", created_guid=guid)
            created.append(item)
        else:
            item.update(status="unknown", error="Missing ID or error; inspect Archicad.")
    return created


async def _group_dispatch(client, receipt):
    created = await _create(
        client,
        receipt,
        "CreatePropertyGroups",
        "propertyGroups",
        "propertyGroupIds",
        "propertyGroupId",
    )
    if not created:
        return
    try:
        groups, _ = await _catalog(
            client, receipt["target"]["port"], receipt["write_timeout_seconds"]
        )
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    found = {_gid(g, "propertyGroupId"): g for g in groups}
    for item in created:
        row = found.get(item["created_guid"])
        wanted = item["parameters"]["propertyGroup"]
        item["after"] = row
        problems = (
            ["missing"]
            if row is None
            else [
                k
                for k, ok in (
                    ("name", row.get("name") == wanted["name"]),
                    ("description", row.get("description", "") == wanted["description"]),
                    ("isCustom", row.get("isCustom") is True),
                )
                if not ok
            ]
        )
        item["status"] = "verification_failed" if problems else "verified"
        if problems:
            item["mismatches"] = problems


def _property_mismatches(item: dict, row: dict | None) -> list[str]:
    if row is None:
        return ["missing"]
    wanted = item["parameters"]["propertyDefinition"]
    shape = _shape(wanted["type"])
    checks = [
        ("name", row.get("propertyName") == wanted["name"]),
        ("group", _gid(row, "propertyGroupId") == item["group_guid"]),
        ("description", row.get("propertyDescription", "") == wanted["description"]),
        ("propertyCollectionType", row.get("propertyCollectionType") == shape["collection"]),
        ("propertyValueType", row.get("propertyValueType") == shape["value"]),
        ("propertyMeasureType", row.get("propertyMeasureType") == shape["measure"]),
        ("isEditable", row.get("propertyIsEditable") == wanted["isEditable"]),
    ]
    stored = {
        _gid(a, "classificationItemId") for a in row.get("availability", []) if isinstance(a, dict)
    }
    asked = {a["classificationItemId"]["guid"] for a in wanted["availability"]}
    checks.append(("availability", stored == asked))
    options = [
        e.get("enumValue", {}) for e in row.get("possibleEnumValues", []) if isinstance(e, dict)
    ]
    if "possibleEnumValues" in wanted:
        asked_values = [e["enumValue"]["displayValue"] for e in wanted["possibleEnumValues"]]
        checks.append(("enum_values", [o.get("displayValue") for o in options] == asked_values))
        default = wanted.get("defaultValue", {}).get("basicDefaultValue", {}).get("value")
        if default is not None:
            ids = default if isinstance(default, list) else [{"enumValueId": default}]
            names = [i["enumValueId"]["displayValue"] for i in ids]
            by_guid = {classifications._guid(o.get("guid")): o.get("displayValue") for o in options}
            got = [
                by_guid.get(classifications._guid(i.get("guid")))
                for i in row.get("defaultEnumValueIds", [])
                if isinstance(i, dict)
            ]
            checks.append(("default", sorted(map(str, got)) == sorted(names)))
    return [k for k, ok in checks if not ok]


async def _property_dispatch(client, receipt):
    created = await _create(
        client,
        receipt,
        "CreatePropertyDefinitions",
        "propertyDefinitions",
        "propertyIds",
        "propertyId",
    )
    if not created:
        return
    try:
        _, properties = await _catalog(
            client, receipt["target"]["port"], receipt["write_timeout_seconds"]
        )
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    found = {_gid(p, "propertyId"): p for p in properties}
    for item in created:
        row = found.get(item["created_guid"])
        item["after"] = row
        if row is not None and "defaultValueDisplay" in row:
            item["default_display"] = row["defaultValueDisplay"]
        problems = _property_mismatches(item, row)
        item["status"] = "verification_failed" if problems else "verified"
        if problems:
            item["mismatches"] = problems


async def create_property_groups(
    client: ArchicadClient,
    groups: list[dict | PropertyGroupCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 new, empty custom property groups."""
    if not 1 <= len(groups) <= MAX_GROUPS:
        raise ValueError(f"Pass between 1 and {MAX_GROUPS} groups.")
    validated = [
        g if isinstance(g, PropertyGroupCreate) else PropertyGroupCreate.model_validate(g)
        for g in groups
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_property_groups",
        planner_override=_group_plan,
        dispatcher_override=_group_dispatch,
    )


async def create_properties(
    client: ArchicadClient,
    properties: list[dict | PropertyCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 50 new custom properties in existing custom groups."""
    if not 1 <= len(properties) <= MAX_PROPERTIES:
        raise ValueError(f"Pass between 1 and {MAX_PROPERTIES} properties.")
    validated = [
        p if isinstance(p, PropertyCreate) else PropertyCreate.model_validate(p) for p in properties
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_properties",
        planner_override=_property_plan,
        dispatcher_override=_property_dispatch,
    )
