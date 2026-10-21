"""Text labels, free or attached to an element (Tapir CreateLabels).

Coordinates in metres. A label attached to an element follows it and sits on its story;
a free label needs a position and a story. The size is height_mm in paper millimetres.
Omitted style fields keep the Label tool default. Never saves.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import read, texts, write

MAX_LABELS = 20


class LabelCreate(write._Favored):
    text: Annotated[str, Field(min_length=1, max_length=2000)]
    element_guid: str | None = None
    position: write.Point | None = None
    floor_index: int | None = None
    height_mm: write.Positive | None = None

    @field_validator("text")
    @classmethod
    def visible(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank.")
        return texts._lines(value)

    @field_validator("element_guid")
    @classmethod
    def canonical_guid(cls, value: str | None) -> str | None:
        return None if value is None else str(UUID(value)).upper()

    @model_validator(mode="after")
    def placed(self) -> LabelCreate:
        if self.element_guid is not None:
            if self.floor_index is not None:
                raise ValueError("an attached label sits on its element's story; omit floor_index.")
        elif self.position is None or self.floor_index is None:
            raise ValueError("a free label needs position and floor_index (or an element_guid).")
        return self


async def _plan(client, labels, port, operation):
    port, target, indices = await write._context(client, port)
    parents = list(dict.fromkeys(lb.element_guid for lb in labels if lb.element_guid))
    owners: dict[str, dict] = {}
    if parents:
        response = await client.tapir(
            port,
            "GetDetailsOfElements",
            {"elements": read.element_ids(parents), "fields": write.DETAIL_FIELDS},
        )
        rows = response.get("detailsOfElements")
        if not isinstance(rows, list) or len(rows) != len(parents):
            raise ValueError("Unexpected element details response.")
        for guid, row in zip(parents, rows, strict=True):
            if not isinstance(row, dict) or "error" in row or row.get("type") in (None, "Unknown"):
                raise ValueError(f"Element {guid} does not exist or cannot be read.")
            owners[guid] = row
    items = []
    for index, label in enumerate(labels):
        payload: dict[str, Any] = {"labelClass": "Text", "text": label.text}
        item: dict[str, Any] = {"index": index, "status": "ready"}
        if label.element_guid:
            owner = owners[label.element_guid]
            payload["parentElementId"] = {"guid": label.element_guid}
            item.update(
                attached_to=label.element_guid,
                attached_type=owner.get("type"),
                floorIndex=owner.get("floorIndex"),
            )
        else:
            if label.floor_index not in indices:
                raise ValueError(f"Label {index}: story {label.floor_index} does not exist.")
            payload["floorInd"] = label.floor_index
            item["floorIndex"] = label.floor_index
        if label.position is not None:
            payload["begCoordinate"] = label.position.model_dump()
        if label.height_mm is not None:
            payload["style"] = {"height": label.height_mm}
        if label.favorite is not None:
            payload["favoriteName"] = label.favorite
        item["parameters"] = payload
        items.append(item)
    await write._resolve_favorites(client, port, "Label", labels, items)
    return {"operation": operation, "target": target, "items": items}


def _mismatches(item: dict, row: Any) -> list[str]:
    p = item["parameters"]
    details: dict[str, Any] = {"labelClass": "Text"}
    if "begCoordinate" in p:
        details["begCoordinate"] = p["begCoordinate"]
    if "style" in p:
        details["style"] = p["style"]
    expected: dict[str, Any] = {"type": "Label", "details": details}
    if item.get("floorIndex") is not None:
        expected["floorIndex"] = item["floorIndex"]
    differences = write._mismatches(expected, row)
    actual = row.get("details") if isinstance(row, dict) else None
    actual = actual if isinstance(actual, dict) else {}
    found = actual.get("text")
    if not isinstance(found, str) or texts._lines(found) != p["text"]:
        differences.append("details.text")
    if "parentElementId" in p:
        owner = actual.get("ownerElementId")
        guid = owner.get("guid") if isinstance(owner, dict) else None
        if not isinstance(guid, str) or guid.upper() != p["parentElementId"]["guid"]:
            differences.append("details.ownerElementId")
    return differences


async def _dispatch(client, receipt):
    await write._dispatch(client, receipt, _mismatches)


async def create_labels(
    client: ArchicadClient,
    labels: list[dict | LabelCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 text labels. Metres; height_mm in paper millimetres.

    With element_guid the label is attached to that element (and its story); without it,
    position and floor_index are needed. Newlines make several lines.
    """
    if not 1 <= len(labels) <= MAX_LABELS:
        raise ValueError(f"Pass between 1 and {MAX_LABELS} labels.")
    validated = [
        lb if isinstance(lb, LabelCreate) else LabelCreate.model_validate(lb) for lb in labels
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_labels",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
