"""Text labels, free or attached to an element (Tapir CreateLabels), and keynote labels.

Coordinates in metres. A label attached to an element follows it and sits on its story;
a free label needs a position and a story. The size is height_mm in paper millimetres.
Omitted style fields keep the Label tool default. Keynote labels (CreateKeynoteLabels,
Archicad 28 or newer) are free labels whose text is the keynote item's autotext; Tapir
puts them on the story Archicad shows and attaches them to nothing. Never saves.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import keynotes, read, texts, write

MAX_LABELS = 20
KeynoteField = Literal["Key", "Title", "Description", "Reference"]


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


class KeynoteLabelCreate(write.InputModel):
    keynote_item_guid: str
    position: write.Point
    content_fields: Annotated[list[KeynoteField], Field(min_length=1, max_length=4)] | None = None

    @field_validator("keynote_item_guid")
    @classmethod
    def canonical_guid(cls, value: str) -> str:
        return str(UUID(value)).upper()

    @field_validator("content_fields")
    @classmethod
    def no_repeats(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("content_fields must not repeat a field.")
        return value


async def _keynote_plan(client, labels, port, operation):
    port, target, _ = await write._context(client, port)
    _, known = await keynotes._tree(client, port)
    by_guid = {row["guid"]: row for row in known if row["guid"]}
    items = []
    for index, label in enumerate(labels):
        found = by_guid.get(label.keynote_item_guid)
        if found is None:
            raise ValueError(
                f"Keynote label {index}: no keynote item {label.keynote_item_guid}; "
                "use list_keynotes."
            )
        payload: dict[str, Any] = {
            "keynoteItemId": {"guid": label.keynote_item_guid},
            "position": label.position.model_dump(),
        }
        if label.content_fields is not None:
            payload["contentFields"] = list(label.content_fields)
        items.append(
            {
                "index": index,
                "status": "ready",
                "keynote": {k: found.get(k) for k in ("key", "title", "path")},
                "parameters": payload,
            }
        )
    return {"operation": operation, "target": target, "items": items}


def _keynote_mismatches(item: dict, row: Any) -> list[str]:
    expected = {
        "type": "Label",
        "details": {"labelClass": "Text", "begCoordinate": item["parameters"]["position"]},
    }
    return write._mismatches(expected, row)


async def _keynote_dispatch(client, receipt):
    await write._dispatch(client, receipt, _keynote_mismatches)
    for item in receipt["items"]:
        row = item.get("after")
        if isinstance(row, dict):
            details = row.get("details") if isinstance(row.get("details"), dict) else {}
            item["floorIndex"] = row.get("floorIndex")
            item["text_read"] = details.get("text")


async def create_keynote_labels(
    client: ArchicadClient,
    labels: list[dict | KeynoteLabelCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 keynote labels at points in metres (Archicad 28+).

    Each label shows the keynote item's fields (all, or content_fields) as autotext.
    It lands on the story Archicad shows and is not attached to an element. The
    keynotes themselves are never changed.
    """
    if not 1 <= len(labels) <= MAX_LABELS:
        raise ValueError(f"Pass between 1 and {MAX_LABELS} keynote labels.")
    validated = [
        lb if isinstance(lb, KeynoteLabelCreate) else KeynoteLabelCreate.model_validate(lb)
        for lb in labels
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_keynote_labels",
        planner_override=_keynote_plan,
        dispatcher_override=_keynote_dispatch,
    )
