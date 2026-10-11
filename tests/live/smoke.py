"""Manual smoke runner. Importing this module never connects to Archicad."""

import argparse
import asyncio
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import read, write

REPOSITORY = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_DIR = Path.home() / ".archicad-mcp-aberto" / "smoke"


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--port", type=int, required=True, help="Explicit Archicad port")
    result.add_argument(
        "--write", action="store_true", help="Create test walls/slab/column in an untitled project"
    )
    result.add_argument(
        "--report-dir",
        type=Path,
        default=DEFAULT_REPORT_DIR,
        help="JSON report directory outside the repository",
    )
    return result


def _save(report: dict, path: Path) -> None:
    # Replace atomically; never overwrite another run's report.
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )
    temporary.replace(path)


async def _untitled(client: ArchicadClient, port: int) -> dict:
    project = await read.get_project_info(client, port)
    if project.get("isUntitled") is not True:
        raise ValueError("--write requires an explicitly untitled project (isUntitled=true).")
    return project


async def _corner(client: ArchicadClient, port: int) -> dict:
    elements, offset = [], 0
    while True:
        page = await read.list_elements(client, port, offset=offset, limit=500)
        elements.extend(page["elements"])
        offset += len(page["elements"])
        if offset >= page["total"]:
            break
        if not page["elements"]:
            raise ValueError("Cannot establish complete element extent.")
    x, y = 20.0, 20.0
    boxes = []
    for offset in range(0, len(elements), 100):
        batch = elements[offset : offset + 100]
        result = await client.command(port, "Get2DBoundingBoxes", {"elements": batch})
        rows = result["boundingBoxes2D"]
        if len(rows) != len(batch):
            raise ValueError("Cannot establish complete bounding boxes.")
        for row in rows:
            box = row.get("boundingBox2D")
            if not isinstance(box, dict) or not all(
                isinstance(box.get(k), (int, float))
                and not isinstance(box[k], bool)
                and math.isfinite(box[k])
                for k in ("xMin", "yMin", "xMax", "yMax")
            ):
                raise ValueError("Cannot establish a free corner: missing or invalid bounding box.")
            if box["xMin"] > box["xMax"] or box["yMin"] > box["yMax"]:
                raise ValueError("Invalid bounding box extent.")
            boxes.append(box)
            x, y = max(x, box["xMax"] + 10), max(y, box["yMax"] + 10)
    return {
        "x": x,
        "y": y,
        "margin_m": 10,
        "bounding_boxes": boxes,
        "note": "Beyond reported floor-plan extents. Operator must check the active floor plan.",
    }


def _check_receipt(receipt: dict, count: int, item_id: str) -> None:
    items = receipt.get("items", [])
    if (
        receipt.get("status") != "verified"
        or len(items) != count
        or receipt.get("counts", {}).get("verified") != count
        or receipt.get("receipt_error")
    ):
        raise ValueError("Write receipt needs review; do not retry or automatically clean up.")
    if any(
        i.get("status") != "verified"
        or not i.get("element_guid")
        or not i.get(item_id)
        or "after" not in i
        for i in items
    ):
        raise ValueError("Incomplete per-element verification receipt.")


async def run_smoke(
    client: ArchicadClient,
    *,
    port: int,
    write_enabled: bool = False,
    report_dir: Path = DEFAULT_REPORT_DIR,
) -> dict:
    """Run through an active client. Unit tests inject MockTransport; CLI uses localhost."""
    if isinstance(port, bool) or not isinstance(port, int) or not 19723 <= port <= 19743:
        raise ValueError("An explicit Archicad port between 19723 and 19743 is required.")
    directory = Path(report_dir).expanduser().resolve()
    if directory == REPOSITORY or REPOSITORY in directory.parents:
        raise ValueError("Reports must be outside the repository.")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"smoke-{datetime.now(UTC):%Y%m%dT%H%M%S}-{uuid4()}.json"
    report = {
        "port": port,
        "write_enabled": write_enabled,
        "status": "running",
        "started_at": datetime.now(UTC).isoformat(),
        "report_path": str(path),
        "reads": {},
        "writes": [],
        "note": "Never saves or deletes. Use manual Undo after inspection.",
    }
    _save(report, path)  # A report failure here prevents any model traffic.
    try:
        reads = report["reads"]
        reads["discovery"] = await read.discover_archicad(client)
        reads["project"] = await read.get_project_info(client, port)
        if write_enabled:
            await _untitled(client, port)
        reads["stories"] = await read.get_stories(client, port)
        reads["elements"] = await read.list_elements(client, port)
        walls = await read.list_elements(client, port, element_type="Wall", limit=5)
        reads["walls"] = walls
        ids = [e["elementId"]["guid"] for e in walls["elements"]]
        reads["wall_details"] = (
            await read.get_element_details(
                client, ids, port, fields=["type", "floorIndex", "details", "floorPlanPolygons"]
            )
            if ids
            else {"detailsOfElements": [], "note": "No walls to read."}
        )
        if write_enabled:
            report["corner"] = await _corner(client, port)
            x, y = report["corner"]["x"], report["corner"]["y"]
            stories = reads["stories"]["stories"]
            if not stories:
                raise ValueError("No story available for smoke writes.")
            story = next((s for s in stories if s["index"] == 0), stories[0])
            report["story"] = story
            wall_inputs = [
                {
                    "start": {"x": x, "y": y},
                    "end": {"x": x + 4, "y": y},
                    "floor_index": story["index"],
                    "height": 3,
                    "thickness": 0.2,
                },
                {
                    "start": {"x": x + 4, "y": y},
                    "end": {"x": x + 4, "y": y + 3},
                    "floor_index": story["index"],
                    "height": 3,
                    "thickness": 0.2,
                },
            ]
            slab_inputs = [
                {
                    "outline": [
                        {"x": x + 6, "y": y},
                        {"x": x + 10, "y": y},
                        {"x": x + 10, "y": y + 3},
                        {"x": x + 6, "y": y + 3},
                    ],
                    "floor_index": story["index"],
                    "thickness": 0.2,
                    "level": story["level"],
                }
            ]
            column_inputs = [
                {
                    "origin": {"x": x + 12, "y": y},
                    "floor_index": story["index"],
                    "height": 3,
                    "base_level": story["level"],
                    "width": 0.3,
                    "depth": 0.5,
                }
            ]
            for tool, inputs, count, item_id in (
                (write.create_walls, wall_inputs, 2, "wall_receipt_id"),
                (write.create_slabs, slab_inputs, 1, "slab_receipt_id"),
                (write.create_columns, column_inputs, 1, "column_receipt_id"),
            ):
                await _untitled(client, port)
                entry = {"tool": tool.__name__, "inputs": inputs}
                report["writes"].append(entry)
                entry["preview"] = await tool(client, inputs, port=port, dry_run=True)
                _save(report, path)
                await _untitled(client, port)
                entry["receipt"] = await tool(
                    client,
                    inputs,
                    port=port,
                    dry_run=False,
                    confirmation_token=entry["preview"]["confirmation_token"],
                )
                _save(report, path)
                _check_receipt(entry["receipt"], count, item_id)
        report["status"] = "passed"
    except Exception as exc:
        report.update(status="failed", error={"type": type(exc).__name__, "message": str(exc)})
    finally:
        report["finished_at"] = datetime.now(UTC).isoformat()
        _save(report, path)
    return report


async def _main(args) -> int:
    async with ArchicadClient() as client:
        report = await run_smoke(
            client, port=args.port, write_enabled=args.write, report_dir=args.report_dir
        )
    print(f"{report['status']}: {report['report_path']}")
    return 0 if report["status"] == "passed" else 1


def main() -> int:
    return asyncio.run(_main(parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
