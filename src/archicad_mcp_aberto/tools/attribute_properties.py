"""Property values of attributes (Tapir 1.7.0 SetPropertyValuesOfAttributes).

Building materials, composites, profiles and other attributes can carry custom property
values. Tapir reads and writes them as display text: Archicad converts the text to the
property's type with the project's own formats, so a value is sent exactly as given and
read back as text. The preview shows the current text of each value and refuses
read-only properties and properties not available for that attribute. Never saves.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import edit, write

MAX_CHANGES = 100


class AttributePropertyChange(write.InputModel):
    attribute_guid: str
    property_guid: str
    value: Annotated[str, Field(max_length=10000)]

    @field_validator("attribute_guid", "property_guid")
    @classmethod
    def canonical_guid(cls, value: str) -> str:
        return str(UUID(value)).upper()


async def _read(client, port, pairs, timeout=None) -> dict[tuple[str, str], Any]:
    """The current {"propertyValue": {"value": text}} or {"error": ...} of each pair."""
    attributes = list(dict.fromkeys(a for a, _ in pairs))
    properties = list(dict.fromkeys(p for _, p in pairs))
    extra = {} if timeout is None else {"timeout": timeout}
    response = await client.tapir(
        port,
        "GetPropertyValuesOfAttributes",
        {
            "attributeIds": [{"attributeId": {"guid": g}} for g in attributes],
            "properties": [{"propertyId": {"guid": g}} for g in properties],
        },
        **extra,
    )
    rows = response.get("propertyValuesForAttributes")
    if not isinstance(rows, list) or len(rows) != len(attributes):
        raise ValueError("Unexpected attribute property value response cardinality.")
    out = {}
    for attribute, row in zip(attributes, rows, strict=True):
        values = row.get("propertyValues") if isinstance(row, dict) else None
        for index, prop in enumerate(properties):
            if (attribute, prop) not in pairs:
                continue
            if isinstance(values, list) and len(values) == len(properties):
                out[(attribute, prop)] = values[index]
            else:
                out[(attribute, prop)] = {
                    "error": row.get("error") if isinstance(row, dict) else row
                }
    return out


def _text(row: Any) -> str | None:
    value = row.get("propertyValue") if isinstance(row, dict) else None
    text = value.get("value") if isinstance(value, dict) else None
    return text if isinstance(text, str) else None


async def _plan(client, changes, port, operation):
    port, target, _ = await write._context(client, port)
    pairs = [(c.attribute_guid, c.property_guid) for c in changes]
    current = await _read(client, port, pairs)
    definitions = await client.command(
        port,
        "GetDetailsOfProperties",
        {"properties": [{"propertyId": {"guid": g}} for g in dict.fromkeys(p for _, p in pairs)]},
    )
    by_guid = {}
    for row in definitions.get("propertyDefinitions", []):
        definition = row.get("propertyDefinition") if isinstance(row, dict) else None
        identifier = definition.get("propertyId") if isinstance(definition, dict) else None
        if isinstance(identifier, dict) and identifier.get("guid"):
            by_guid[str(identifier["guid"]).upper()] = definition
    items = []
    for index, change in enumerate(changes):
        label = f"Change {index} ({change.attribute_guid} / {change.property_guid})"
        definition = by_guid.get(change.property_guid)
        if definition is None:
            raise ValueError(f"{label}: the property does not exist.")
        if definition.get("isEditable") is False:
            raise ValueError(f"{label}: the property is read-only.")
        row = current[(change.attribute_guid, change.property_guid)]
        before = _text(row)
        if before is None:
            error = row.get("error") if isinstance(row, dict) else row
            raise ValueError(f"{label}: not available for this attribute ({error}).")
        items.append(
            {
                "index": index,
                "status": "ready",
                "attribute_guid": change.attribute_guid,
                "property_guid": change.property_guid,
                "property_name": definition.get("name"),
                "before": before,
                "parameters": {
                    "attributeId": {"guid": change.attribute_guid},
                    "propertyId": {"guid": change.property_guid},
                    "propertyValue": {"value": change.value},
                },
            }
        )
    return {"operation": operation, "target": target, "items": items}


async def _verify(client, receipt, items):
    after = await _read(
        client,
        receipt["target"]["port"],
        [(i["attribute_guid"], i["property_guid"]) for i in items],
        receipt["write_timeout_seconds"],
    )
    for item in items:
        row = after[(item["attribute_guid"], item["property_guid"])]
        item["after"] = _text(row) if _text(row) is not None else row
        if item["after"] == item["parameters"]["propertyValue"]["value"]:
            item["status"] = "verified"
        else:
            item.update(status="verification_failed", mismatches=["propertyValue"])


async def _dispatch(client, receipt):
    await edit._execute(
        client, receipt, "SetPropertyValuesOfAttributes", "attributePropertyValues", _verify
    )


async def set_attribute_property_values(
    client: ArchicadClient,
    changes: list[dict | AttributePropertyChange],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 100 attribute property values, each as display text."""
    if not 1 <= len(changes) <= MAX_CHANGES:
        raise ValueError(f"Pass between 1 and {MAX_CHANGES} property changes.")
    validated = [
        c if isinstance(c, AttributePropertyChange) else AttributePropertyChange.model_validate(c)
        for c in changes
    ]
    pairs = [(c.attribute_guid, c.property_guid) for c in validated]
    if len(set(pairs)) != len(pairs):
        raise ValueError("Each attribute and property pair may appear only once per call.")
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "set_attribute_property_values",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
