"""Plain text elements on a story (Tapir CreateTexts).

Position in metres, angle in radians. Archicad sizes text in paper millimetres, so the
height is height_mm. Omitted style fields keep the Text tool default. Never saves.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import write

MAX_TEXTS = 20


def _lines(text: str) -> str:
    # Tapir turns CRLF and bare CR into LF on create; compare in the same form.
    return text.replace("\r\n", "\n").replace("\r", "\n")


class TextCreate(write.InputModel):
    text: Annotated[str, Field(min_length=1, max_length=2000)]
    position: write.Point
    floor_index: int
    angle: float = 0.0
    height_mm: write.Positive | None = None
    justification: Literal["Left", "Center", "Right", "Full"] | None = None

    @field_validator("text")
    @classmethod
    def visible(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be blank.")
        return _lines(value)


def _payload(text: TextCreate, story_level: float) -> dict:
    payload: dict[str, Any] = {
        "coordinate": {**text.position.model_dump(), "z": story_level},
        "floorIndex": text.floor_index,
        "text": text.text,
        "angle": text.angle,
    }
    if text.height_mm is not None:
        payload["height"] = text.height_mm
    if text.justification is not None:
        payload["justification"] = text.justification
    return payload


async def _plan(client, texts, port, operation):
    port, target, _ = await write._context(client, port)
    levels = {s["index"]: s["level"] for s in target["stories"]}
    items = []
    for index, text in enumerate(texts):
        if text.floor_index not in levels:
            raise ValueError(f"Text {index}: story {text.floor_index} does not exist.")
        items.append(
            {
                "index": index,
                "status": "ready",
                "parameters": _payload(text, levels[text.floor_index]),
            }
        )
    return {"operation": operation, "target": target, "items": items}


def _mismatches(item: dict, row: Any) -> list[str]:
    p = item["parameters"]
    details: dict[str, Any] = {
        "position": {"x": p["coordinate"]["x"], "y": p["coordinate"]["y"]},
    }
    for key in ("height", "justification"):
        if key in p:
            details[key] = p[key]
    differences = write._mismatches(
        {"type": "Text", "floorIndex": p["floorIndex"], "details": details}, row
    )
    actual = row.get("details") if isinstance(row, dict) else None
    actual = actual if isinstance(actual, dict) else {}
    found = actual.get("text")
    if not isinstance(found, str) or _lines(found) != p["text"]:
        differences.append("details.text")
    angle = actual.get("angle")
    if (
        not isinstance(angle, (int, float))
        or isinstance(angle, bool)
        or not math.isfinite(angle)
        or abs(math.remainder(angle - p["angle"], math.tau)) > 1e-7
    ):
        differences.append("details.angle")
    return differences


async def _dispatch(client, receipt):
    await write._dispatch(client, receipt, _mismatches)


async def create_texts(
    client: ArchicadClient,
    texts: list[dict | TextCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 plain texts on stories. Metres, radians, height_mm in mm.

    Newlines make several lines. Font and other style come from the Text tool default.
    """
    if not 1 <= len(texts) <= MAX_TEXTS:
        raise ValueError(f"Pass between 1 and {MAX_TEXTS} texts.")
    validated = [t if isinstance(t, TextCreate) else TextCreate.model_validate(t) for t in texts]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "create_texts",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
