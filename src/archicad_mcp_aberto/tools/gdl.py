"""GDL parameter knowledge shared by the read, edit and general parameter tools.

Source: Tapir ``ElementGDLParameterCommands.cpp`` and ``AddOnMain.cpp`` at tags 1.7.0 to
1.7.3 (read 28/10/2026). Nothing here is a live capture; see docs/PARAMETERS.md.
"""

from __future__ import annotations

import math
from typing import Any

# Element types whose library part parameters Tapir's Get/SetGDLParametersOfElements reach.
# The command looks the library part index up for these types only; another type gets a
# libInd of -1, so the MCP never sends it (stairs and railing parts included).
GDL_OWNER_TYPES = (
    "Object",
    "Lamp",
    "Window",
    "Door",
    "Skylight",
    "Zone",
    "Label",
    "Drawing",
    "CurtainWallFrame",
    "CurtainWallPanel",
    "CurtainWallJunction",
    "CurtainWallAccessory",
)
# Types whose A/B Tapir also copies back to the element's own size after a write.
SIZE_LINKED_TYPES = ("Object", "Lamp", "Window", "Door", "Skylight")
# Types whose GDL write was read back on a real Archicad (AC30 3001 BRA, see VALIDAR.md).
LIVE_WRITE_TYPES = ("Object",)
MARKER_TYPES = ("Window", "Door")

MARKER_SINCE = (1, 7, 1)  # Get/SetMarkerParametersOfElements registered
ARRAY_WRITE_SINCE = (1, 7, 2)  # arrays written through ChangeAParameter (Tapir #557)
ANGLE_RADIANS_SINCE = (1, 7, 3)  # before, written Angle values were taken in degrees (#1401)
SCRIPT_SINCE = (1, 7, 3)  # RunParameterScriptOfElements registered

BLOCKING_FLAGS = ("Fixed", "Hidden", "HiddenFromScript", "Disabled")
UNITS = {
    "Length": "m",
    "Angle": "rad",
    "RealNumber": None,
    "Integer": None,
    "Intensity": None,
    "RGBColor": "0..1",
    "Boolean": "true/false",
    "LightSwitch": "On/Off",
    "String": "text",
    "Title": "text",
    "PenColor": "pen index",
    "LineType": "line type index",
    "Material": "surface index",
    "FillPattern": "fill index",
    "BuildingMaterial": "building material index",
    "Profile": "profile index",
    "Dictionary": None,
}
INTEGER_TYPES = {
    "Integer",
    "PenColor",
    "LineType",
    "Material",
    "FillPattern",
    "BuildingMaterial",
    "Profile",
}
REAL_TYPES = {"Length", "Angle", "RealNumber", "Intensity", "RGBColor"}
TOLERANCE = 1e-6


def version(text: Any) -> tuple[int, ...]:
    """Tapir version as a tuple; unreadable text is (0,), so every feature check fails."""
    try:
        return tuple(int(part) for part in str(text).split(".")[:3])
    except ValueError:
        return (0,)


def tapir_version(target: dict) -> tuple[int, ...]:
    tapir = target.get("tapir")
    return version(tapir.get("version") if isinstance(tapir, dict) else None)


def blocked_reason(parameter: dict) -> str | None:
    """Why a parameter must not be written, or None. Mirrors what the dialog lets a user do."""
    flags = parameter.get("flags", [])
    if not isinstance(flags, list):
        return "Unexpected GDL flags."
    hit = [f for f in BLOCKING_FLAGS if f in flags]
    if hit:
        return f"Parameter is {'/'.join(hit)} in the parameter list."
    if parameter.get("isLocked") is True:
        return "Parameter is locked by the library part's parameter script."
    if parameter.get("type") in ("Dictionary", "UNKNOWN", None):
        return f"Type {parameter.get('type')!r} cannot be written through the Archicad API."
    if "value" not in parameter:
        return "Tapir returned no value for this parameter."
    return None


def _options(parameter: dict) -> tuple[list, dict]:
    options, limits = [], {}
    for entry in parameter.get("possibleValues") or []:
        if isinstance(entry, str):
            options.append({"value": entry})
        elif isinstance(entry, dict):
            flag = entry.get("flag")
            if flag in ("GreaterThan", "GreaterThanOrEqual"):
                limits.setdefault("lower", []).append(
                    {"value": entry.get("value"), "inclusive": flag == "GreaterThanOrEqual"}
                )
            elif flag in ("LessThan", "LessThanOrEqual"):
                limits.setdefault("upper", []).append(
                    {"value": entry.get("value"), "inclusive": flag == "LessThanOrEqual"}
                )
            elif flag == "Step":
                limits.setdefault("steps", []).append(
                    {"begin": entry.get("stepBegin"), "step": entry.get("stepValue")}
                )
            else:
                option = {"value": entry.get("value")}
                if entry.get("description"):
                    option["description"] = entry["description"]
                options.append(option)
    return options, limits


def describe(parameters: list) -> list[dict]:
    """Tapir's parameter rows in the inspection shape, keeping order and every native key.

    ``group`` is the nearest Title row above; ``parent`` the nearest non-Child row above
    a Child row. Both come only from the order and flags of the parameter list itself.
    """
    out, group, parent = [], None, None
    for raw in parameters:
        if not isinstance(raw, dict):
            continue
        kind = raw.get("type")
        flags = raw.get("flags") if isinstance(raw.get("flags"), list) else []
        options, limits = _options(raw)
        reason = blocked_reason(raw)
        row = {
            "name": raw.get("name"),
            "description": raw.get("displayName"),
            "index": raw.get("index"),
            "type": kind,
            "unit": UNITS.get(kind),
            "value": raw.get("value"),
            "value_description": raw.get("valueDescription"),
            "flags": flags,
            "is_locked": raw.get("isLocked"),
            "editable": reason is None,
            "edit_blocked_reason": reason,
            "group": group,
            "parent": parent if "Child" in flags else None,
        }
        if raw.get("dimension1") or raw.get("dimension2"):
            row["dimensions"] = [raw.get("dimension1"), raw.get("dimension2")]
            row["item_descriptions"] = raw.get("itemDescriptions")
        if options:
            row["options"] = options
        if limits:
            row["limits"] = limits
        if "canHaveCustomValue" in raw:
            row["custom_value_allowed"] = raw["canHaveCustomValue"]
        out.append(row)
        if kind == "Title":
            group = raw.get("name")
        if "Child" not in flags:
            parent = raw.get("name")
    return out


def _scalar(kind: str, value: Any) -> Any:
    if kind in ("String", "Title"):
        if not isinstance(value, str):
            raise ValueError("requires text")
        return value
    if kind == "Boolean":
        if not isinstance(value, bool):
            raise ValueError("requires true/false")
        return value
    if kind == "LightSwitch":
        if isinstance(value, bool):
            return "On" if value else "Off"
        if value in ("On", "Off"):
            return value
        raise ValueError("requires true/false or 'On'/'Off'")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("requires a number")
    if not math.isfinite(value):
        raise ValueError("requires a finite number")
    if kind in INTEGER_TYPES:
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("requires an integer")
        return int(value)
    if kind in REAL_TYPES:
        return float(value)
    raise ValueError(f"type {kind!r} is not writable")


def _accepted(value: Any, row: dict) -> str | None:
    """Check a scalar against the options and limits the library part reports."""
    options, limits = row.get("options", []), row.get("limits", {})
    if not options and not limits:
        return None
    if isinstance(value, str):
        names = [o["value"] for o in options]
        if names and value not in names and row.get("custom_value_allowed") is not True:
            return f"value must be one of {names}"
        return None
    if isinstance(value, bool):
        return None
    if any(
        isinstance(o["value"], (int, float))
        and not isinstance(o["value"], bool)
        and abs(o["value"] - value) <= TOLERANCE
        for o in options
    ):
        return None
    if row.get("custom_value_allowed") is True:
        return None
    ranges = []
    for low in limits.get("lower", []):
        ok = value >= low["value"] - TOLERANCE if low["inclusive"] else value > low["value"]
        ranges.append(ok)
    for high in limits.get("upper", []):
        ok = value <= high["value"] + TOLERANCE if high["inclusive"] else value < high["value"]
        ranges.append(ok)
    for step in limits.get("steps", []):
        begin, size = step.get("begin"), step.get("step")
        if isinstance(begin, (int, float)) and isinstance(size, (int, float)) and size:
            ratio = (value - begin) / size
            ranges.append(value >= begin - TOLERANCE and abs(ratio - round(ratio)) < 1e-6)
    if ranges and any(ranges):
        return None
    shown = [o["value"] for o in options]
    return f"value is outside the library part's values {shown} and limits {limits}"


def coerce(raw: dict, value: Any, tapir: tuple[int, ...]) -> tuple[Any, Any]:
    """Validate a requested value; return (value as read back, value to send to Tapir).

    Angles are radians on both sides from Tapir 1.7.3; before it the write took degrees.
    """
    reason = blocked_reason(raw)
    if reason:
        raise ValueError(reason)
    row = describe([raw])[0]
    kind = raw["type"]
    dims = row.get("dimensions")
    if dims:
        if tapir < ARRAY_WRITE_SINCE:
            raise ValueError("array parameters need Tapir 1.7.2 or later to be written safely")
        d1, d2 = dims[0] or 0, dims[1] or 1
        if not isinstance(value, list):
            raise ValueError(f"array parameter requires a list of {d1} x {d2} values")
        flat = value
        if value and all(isinstance(v, list) for v in value):
            if len(value) != d1 or any(len(v) != d2 for v in value):
                raise ValueError(f"array parameter has {d1} x {d2} items; resizing is impossible")
            flat = [v for line in value for v in line]
        if len(flat) != d1 * d2:
            raise ValueError(f"array parameter has {d1} x {d2} items; resizing is impossible")
        try:
            expected = [_scalar(kind, v) for v in flat]
        except ValueError as exc:
            raise ValueError(f"array item {exc}") from None
        wire = [_wire(kind, v, tapir) for v in expected]
        return expected, wire
    if isinstance(value, (list, dict)):
        raise ValueError("scalar parameter requires a single value")
    try:
        expected = _scalar(kind, value)
    except ValueError as exc:
        raise ValueError(f"{kind} parameter {exc}") from None
    problem = _accepted(expected, row)
    if problem:
        raise ValueError(problem)
    return expected, _wire(kind, expected, tapir)


def _wire(kind: str, value: Any, tapir: tuple[int, ...]) -> Any:
    if kind == "Angle" and tapir < ANGLE_RADIANS_SINCE:
        return math.degrees(value)
    return value


def same(expected: Any, actual: Any) -> bool:
    if isinstance(expected, list):
        return (
            isinstance(actual, list)
            and len(actual) == len(expected)
            and all(same(a, b) for a, b in zip(expected, actual, strict=True))
        )
    if isinstance(expected, bool) or isinstance(actual, bool):
        return expected is actual
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return abs(expected - actual) <= TOLERANCE
    return expected == actual


def by_name(parameters: Any) -> dict[str, dict]:
    """Rows by name; a duplicated name maps to None so it is never written by guess."""
    out: dict[str, Any] = {}
    for row in parameters if isinstance(parameters, list) else []:
        if isinstance(row, dict) and isinstance(row.get("name"), str):
            out[row["name"]] = None if row["name"] in out else row
    return out
