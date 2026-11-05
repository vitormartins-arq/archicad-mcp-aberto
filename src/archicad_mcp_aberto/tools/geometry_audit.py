"""Bounded, read-only triage of official 3D bounding boxes, without Tapir."""

from __future__ import annotations

import math
from collections import Counter
from typing import Any
from uuid import UUID

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import read

MAX_ELEMENTS = 500


def _finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _positive_finite(name: str, value: float) -> None:
    if not _finite_number(value) or value <= 0:
        raise ValueError(f"{name} must be a positive finite number in metres.")


def _extents(box: dict[str, Any]) -> list[float] | None:
    values = [box.get(f"{axis}{end}") for axis in "xyz" for end in ("Min", "Max")]
    if any(not _finite_number(v) for v in values):
        return None
    extents = [box[f"{axis}Max"] - box[f"{axis}Min"] for axis in "xyz"]
    return extents if all(math.isfinite(v) and v >= 0 for v in extents) else None


async def audit_geometry(
    client: ArchicadClient,
    element_guids: list[str],
    port: int | None = None,
    max_origin_distance_m: float = 10_000.0,
    max_extent_m: float = 500.0,
    offset: int = 0,
    limit: int = 20,
) -> dict[str, Any]:
    """Review 1–500 explicit GUIDs using one official bounding-box batch.

    Report only findings, with full-scope counts and paginated details. Distances
    use the nearest point of each box to the project origin, not a survey point.
    Thresholds are review heuristics, never proof of a modeling defect. Does not
    enumerate the model or change selection/model; no Tapir is required.
    """
    if not 1 <= len(element_guids) <= MAX_ELEMENTS:
        raise ValueError("Pass between 1 and 500 element GUIDs per call.")
    _positive_finite("max_origin_distance_m", max_origin_distance_m)
    _positive_finite("max_extent_m", max_extent_m)
    if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
        raise ValueError("offset must be a non-negative integer.")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= MAX_ELEMENTS:
        raise ValueError("limit must be an integer between 1 and 500.")
    guids = list(dict.fromkeys(str(UUID(g)).upper() for g in element_guids))
    try:
        response = await read.get_bounding_boxes(client, guids, port=port, mode="3d")
    except (KeyError, TypeError) as exc:
        raise ValueError("Unexpected 3D bounding box response shape.") from exc

    findings: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    for row in response["boundingBoxes"]:
        if "error" in row:
            # Unavailable geometry is not a diagnosis of a missing library part.
            issues = [{"code": "bounds_unavailable", "error": row["error"]}]
            finding = {"guid": row["guid"], "issues": issues}
        else:
            box = row["box"]
            extents = _extents(box)
            if extents is None:
                # Do not put NaN/Infinity back into the JSON response.
                issues = [{"code": "invalid_bounds", "message": "Non-finite or inverted bounds."}]
                finding = {"guid": row["guid"], "issues": issues}
            else:
                issues = []
                nearest = [max(box[f"{a}Min"], 0, -box[f"{a}Max"]) for a in "xyz"]
                distance = math.hypot(*nearest)
                if all(v == 0 for v in extents):
                    issues.append({"code": "zero_size_bounds"})
                if max(extents) > max_extent_m:
                    issues.append({"code": "large_extent"})
                if distance > max_origin_distance_m:
                    issues.append({"code": "far_from_origin"})
                finding = {
                    "guid": row["guid"],
                    "issues": issues,
                    "bounds": box,
                    "extents_m": dict(zip("xyz", extents, strict=True)),
                    "min_distance_to_origin_m": distance if math.isfinite(distance) else None,
                }
        if issues:
            findings.append(finding)
            counts.update(issue["code"] for issue in issues)

    page = findings[offset : offset + limit]
    has_more = offset + len(page) < len(findings)
    return {
        "port": response["port"],
        "units": "m",
        "scope": "explicit_guids_only",
        "requested_count": len(element_guids),
        "duplicate_inputs_ignored": len(element_guids) - len(guids),
        "thresholds": {
            "max_origin_distance_m": max_origin_distance_m,
            "max_extent_m": max_extent_m,
        },
        "summary": {
            "checked": len(guids),
            "with_findings": len(findings),
            "without_findings": len(guids) - len(findings),
            "by_code": dict(counts),
        },
        "offset": offset,
        "limit": limit,
        "has_more": has_more,
        "next_offset": offset + len(page) if has_more else None,
        "findings": page,
        "notes": [
            "Review candidates only: bounds cannot prove corrupt geometry, duplicates, "
            "missing library parts, high polygon counts or whole-model health.",
            "Large and georeferenced projects may legitimately exceed the thresholds. "
            "Flat boxes are accepted; a point-sized box can also be intentional.",
            "Scope follows the current 3D bounding-box API; unavailable boxes are reported, "
            "not silently treated as healthy. Pagination re-reads the same requested batch.",
        ],
    }
