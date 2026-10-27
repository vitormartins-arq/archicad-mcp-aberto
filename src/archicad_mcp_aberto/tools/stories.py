"""Add stories above the top one or below the bottom one (Tapir 1.7.0 SetStories).

Tapir's SetStories takes the whole story structure and grows, renames, moves or deletes
stories to match it; deleting a story deletes its elements. add_stories only ever sends
the existing stories exactly as GetStories reads them (index, name, level, section
display) plus the new ones, so the structure only grows. New stories go strictly above
the top story or strictly below the bottom one (basements, negative indices); a level in
between is refused, because it would renumber the stories the elements sit on. The
preview shows every story's height after the change: the old top story's height becomes
the gap to the first new story above it. The read-back is GetStories. Never saves.
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError, TapirError
from archicad_mcp_aberto.tools import write

MAX_STORIES = 20
LEVEL_TOLERANCE = 1e-4  # metres, as Tapir's StoryLevelTolerance
MIN_HEIGHT = 0.01  # metres between two stories
Name = Annotated[str, Field(min_length=1, max_length=255)]


class StoryCreate(write.InputModel):
    name: Name
    level: float
    show_on_sections: bool | None = None

    @field_validator("name")
    @classmethod
    def trimmed(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("story names must not start or end with spaces.")
        return value


def _existing(rows: Any) -> list[dict]:
    if not isinstance(rows, list) or not rows:
        raise ValueError("Cannot read the stories of this project.")
    out = []
    for row in rows:
        if not isinstance(row, dict) or not all(k in row for k in ("index", "name", "level")):
            raise ValueError(f"Unexpected story row ({row}).")
        out.append(
            {
                "index": int(row["index"]),
                "name": str(row["name"]),
                "level": float(row["level"]),
                "dispOnSections": bool(row.get("dispOnSections", True)),
            }
        )
    out.sort(key=lambda s: s["index"])
    if [s["index"] for s in out] != list(range(out[0]["index"], out[0]["index"] + len(out))):
        raise ValueError("The story indices of this project are not consecutive.")
    return out


async def _plan(client, stories, port, operation):
    port, target, _ = await write._context(client, port)
    existing = _existing(target["stories"])
    bottom, top = existing[0], existing[-1]
    taken = {s["name"].casefold() for s in existing}
    above, below = [], []
    for index, story in enumerate(stories):
        if story.name.casefold() in taken:
            raise ValueError(f"Story {index}: the name {story.name!r} is already used.")
        taken.add(story.name.casefold())
        if story.level > top["level"] + MIN_HEIGHT - LEVEL_TOLERANCE:
            above.append(story)
        elif story.level < bottom["level"] - MIN_HEIGHT + LEVEL_TOLERANCE:
            below.append(story)
        else:
            raise ValueError(
                f"Story {index}: level {story.level} m is not above the top story "
                f"({top['name']!r}, {top['level']} m) nor below the bottom one "
                f"({bottom['name']!r}, {bottom['level']} m). Adding between stories would "
                "renumber them; do it in Archicad."
            )
    above.sort(key=lambda s: s.level)
    below.sort(key=lambda s: s.level)
    new = [
        {
            "index": bottom["index"] - len(below) + n,
            "name": s.name,
            "level": s.level,
            "dispOnSections": bottom["dispOnSections"]
            if s.show_on_sections is None
            else s.show_on_sections,
        }
        for n, s in enumerate(below)
    ] + [
        {
            "index": top["index"] + 1 + n,
            "name": s.name,
            "level": s.level,
            "dispOnSections": top["dispOnSections"]
            if s.show_on_sections is None
            else s.show_on_sections,
        }
        for n, s in enumerate(above)
    ]
    structure = sorted(existing + new, key=lambda s: s["index"])
    for lower, upper in zip(structure, structure[1:], strict=False):
        if upper["level"] - lower["level"] < MIN_HEIGHT - LEVEL_TOLERANCE:
            raise ValueError(
                f"Stories {lower['name']!r} and {upper['name']!r} are less than "
                f"{MIN_HEIGHT} m apart."
            )
    heights = {
        lower["index"]: round(upper["level"] - lower["level"], 9)
        for lower, upper in zip(structure, structure[1:], strict=False)
    }
    added = {s["index"] for s in new}
    items = [
        {
            "index": n,
            "status": "ready",
            "story_index": s["index"],
            "name": s["name"],
            "level": s["level"],
            "height_after": heights.get(s["index"]),
            "parameters": s,
        }
        for n, s in enumerate(new)
    ]
    return {
        "operation": operation,
        "target": target,
        "structure_after": [
            {
                "index": s["index"],
                "name": s["name"],
                "level": s["level"],
                "height": heights.get(s["index"]),
                "new": s["index"] in added,
            }
            for s in structure
        ],
        "stories": structure,
        "items": items,
    }


def _same(want: dict, row: Any) -> list[str]:
    if not isinstance(row, dict):
        return ["story"]
    differences = []
    if row.get("name") != want["name"]:
        differences.append("name")
    level = row.get("level")
    if not isinstance(level, int | float) or abs(level - want["level"]) >= LEVEL_TOLERANCE:
        differences.append("level")
    return differences


async def _dispatch(client, receipt):
    items, port = receipt["items"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    try:
        raw = await client.tapir(
            port, "SetStories", {"stories": receipt["stories"]}, timeout=timeout
        )
    except TapirError as exc:
        if not exc.detail:
            unknown = str(exc)
        else:
            unknown = None
            raw = {"success": False, "error": exc.detail}
    except ArchicadError as exc:
        unknown = str(exc)
    else:
        unknown = None
    if unknown is not None:
        for item in items:
            item.update(status="unknown", error=unknown)
        receipt["warning"] = "Outcome is unknown. Inspect the stories; do not retry this plan."
        return
    receipt["raw_response"] = raw
    if raw.get("success") is not True:
        for item in items:
            item.update(status="failed", error=raw.get("error", raw))
        receipt["warning"] = (
            "SetStories failed and may have stopped halfway. Check the stories in Archicad."
        )
    try:
        after = await client.tapir(port, "GetStories", timeout=timeout)
        rows = {int(r["index"]): r for r in after.get("stories", []) if isinstance(r, dict)}
    except (ArchicadError, KeyError, TypeError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    changed = [
        s["name"]
        for s in receipt["stories"]
        if s["index"] not in {i["story_index"] for i in items} and _same(s, rows.get(s["index"]))
    ]
    if changed:
        receipt["existing_stories_changed"] = changed
    if raw.get("success") is not True:
        receipt["stories_after"] = list(rows.values())
        return
    for item in items:
        row = rows.get(item["story_index"])
        item["after"] = row
        differences = _same(item["parameters"], row)
        if changed:
            differences.append("existing stories changed")
        item["status"] = "verification_failed" if differences else "verified"
        if differences:
            item["mismatches"] = differences


async def add_stories(
    client: ArchicadClient,
    stories: list[dict | StoryCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply up to 20 new stories (name, absolute level in metres) above the top
    story or below the bottom one. Existing stories are sent back unchanged."""
    if not 1 <= len(stories) <= MAX_STORIES:
        raise ValueError(f"Pass between 1 and {MAX_STORIES} stories.")
    validated = [
        s if isinstance(s, StoryCreate) else StoryCreate.model_validate(s) for s in stories
    ]
    return await write._write(
        client,
        validated,
        port,
        dry_run,
        confirmation_token,
        "add_stories",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
