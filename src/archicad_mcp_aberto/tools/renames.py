"""Rename template items in bulk (Tapir 1.7.0), for cleaning up an office template.

One call renames one kind of item, either by find and replace on the names or by a list
of exact old -> new names. Kinds: Navigator items (View Map, Project Map, Layout Book),
favorites, classification systems and items, custom property groups and properties,
building materials, surfaces and layers. Every item keeps its GUID, so elements that use
it follow the new name. Renamed View Map items get a custom name, as in Archicad. Model
View Options and Graphic Overrides have no Tapir 1.7.0 command, so they are not here.
Uses the shared preview, single-use token and receipts, and reads every name back.
Never saves.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError, TapirError
from archicad_mcp_aberto.tools import classifications, documents, drafting, write
from archicad_mcp_aberto.tools import favorites as favorites_tool
from archicad_mcp_aberto.tools import property_definitions as pd

MAX_RENAMES = 500
Text = Annotated[str, Field(min_length=1, max_length=255)]
NAVIGATOR = {"view_map": "PublicViewMap", "project_map": "ProjectMap", "layout_book": "LayoutBook"}
# kind -> (Tapir attribute type, create command, data array key)
ATTRIBUTES = {
    "building_materials": (
        "BuildingMaterial",
        "CreateBuildingMaterials",
        "buildingMaterialDataArray",
    ),
    "surfaces": ("Surface", "CreateSurfaces", "surfaceDataArray"),
    "layers": ("Layer", "CreateLayers", "layerDataArray"),
}
# Element types whose favorites are searched (the tools a template keeps favorites for).
FAVORITE_TYPES = (
    "Wall", "Column", "Beam", "Window", "Door", "Object", "Lamp", "Slab", "Roof", "Mesh",
    "Zone", "CurtainWall", "Shell", "Skylight", "Morph", "Stair", "Railing", "Opening",
    "Dimension", "Text", "Label", "Hatch", "Line", "PolyLine", "Arc", "Circle", "Spline",
    "Hotspot", "Detail", "Worksheet", "Elevation", "InteriorElevation", "CutPlane",
)  # fmt: skip
Kind = Literal[
    "view_map",
    "project_map",
    "layout_book",
    "favorites",
    "classification_systems",
    "classification_items",
    "property_groups",
    "properties",
    "building_materials",
    "surfaces",
    "layers",
]


class Rename(write.InputModel):
    old: Text
    new: Text


class RenameRequest(write.InputModel):
    kind: Kind
    renames: Annotated[list[Rename], Field(min_length=1, max_length=MAX_RENAMES)] | None = None
    find: Text | None = None
    replace: Annotated[str, Field(max_length=255)] | None = None
    scope: Text | None = None  # classification system, property group or favorite type

    @model_validator(mode="after")
    def one_way(self):
        if (self.renames is None) == (self.find is None):
            raise ValueError("Pass either renames (old -> new) or find and replace.")
        if self.find is not None and self.replace is None:
            raise ValueError("find needs replace (an empty text removes it).")
        if self.renames is not None:
            olds = [r.old for r in self.renames]
            if len(set(olds)) != len(olds):
                raise ValueError("Each old name may appear only once.")
        if any(not r.new.strip() for r in self.renames or []):
            raise ValueError("A new name must not be blank.")
        if self.scope is not None and self.kind not in (
            "classification_items",
            "properties",
            "favorites",
        ):
            raise ValueError("scope is only for classification_items, properties and favorites.")
        return self


def _nav_rows(node: Any, depth: int, path: str, out: list[dict]) -> list[dict]:
    if not isinstance(node, dict):
        return out
    guid = documents._guid(node.get("navigatorItemId"))
    name = node.get("name")
    if guid and depth > 0 and isinstance(name, str):  # the map's root is not renamed
        out.append({"key": guid, "fields": {"name": name}, "where": path, "type": node.get("type")})
    children = node.get("children") if isinstance(node.get("children"), list) else []
    for child in children:
        item = child.get("navigatorItem") if isinstance(child, dict) else None
        _nav_rows(item, depth + 1, f"{path}/{name}" if depth > 0 else "", out)
    return out


async def _catalog(client, port, request: RenameRequest, timeout=None) -> list[dict]:
    """Rows of {key, fields {field: text}, where}: what this kind can rename."""
    kind, extra = request.kind, ({} if timeout is None else {"timeout": timeout})
    if kind in NAVIGATOR:
        response = await client.tapir(
            port, "GetNavigatorItemTree", {"navigatorMapId": NAVIGATOR[kind]}, **extra
        )
        root = response.get("navigatorItemTree")
        if not isinstance(root, dict):
            raise ValueError(f"Unexpected {NAVIGATOR[kind]} navigator response.")
        return _nav_rows(root, 0, "", [])
    if kind == "favorites":
        types = FAVORITE_TYPES
        if request.scope is not None:
            types = tuple(t for t in FAVORITE_TYPES if t.casefold() == request.scope.casefold())
            if not types:
                raise ValueError(f"Favorite type {request.scope!r} is not supported.")
        rows: dict[str, dict] = {}
        for element_type in types:
            for name in await favorites_tool._names(client, port, element_type):
                row = rows.setdefault(name, {"key": name, "fields": {"name": name}, "where": ""})
                row["where"] = f"{row['where']}, {element_type}".lstrip(", ")
        return list(rows.values())
    if kind in ("classification_systems", "classification_items"):
        systems = await classifications._systems(client, port)
        if kind == "classification_systems":
            return [
                {"key": s["guid"], "fields": {"name": s.get("name") or ""}, "where": ""}
                for s in systems
            ]
        if request.scope is not None:
            systems = [classifications._pick_system(systems, request.scope)]
        out = []
        for system in systems:
            for item in await classifications._items(client, port, system["guid"]):
                fields = {"id": item.get("id") or "", "name": item.get("name") or ""}
                out.append({"key": item["guid"], "fields": fields, "where": system.get("name")})
        return out
    if kind in ("property_groups", "properties"):
        groups, props = await pd._catalog(client, port, timeout)
        custom = {pd._gid(g, "propertyGroupId"): g for g in groups if g.get("isCustom") is True}
        if kind == "property_groups":
            return [
                {"key": k, "fields": {"name": g["name"]}, "where": ""} for k, g in custom.items()
            ]
        if request.scope is not None:
            group = pd._pick_group(list(custom.values()), request.scope)
            custom = {pd._gid(group, "propertyGroupId"): group}
        return [
            {
                "key": pd._gid(p, "propertyId"),
                "fields": {"name": p.get("propertyName") or ""},
                "where": custom[pd._gid(p, "propertyGroupId")]["name"],
            }
            for p in props
            if pd._gid(p, "propertyGroupId") in custom and pd._gid(p, "propertyId")
        ]
    attribute_type = ATTRIBUTES[kind][0]
    rows = await drafting._attributes(client, port, attribute_type)
    return [
        {"key": documents._guid(r.get("attributeId")), "fields": {"name": r["name"]}, "where": ""}
        for r in rows
        if documents._guid(r.get("attributeId"))
    ]


def _unique_scope(kind: str, row: dict) -> str | None:
    """Names must stay unique within this scope (None: duplicates are allowed)."""
    if kind in NAVIGATOR:
        return None
    if kind in ("classification_items", "properties"):
        return str(row["where"])
    return ""


def _parameters(kind: str, key: str, new: dict) -> dict:
    if kind in NAVIGATOR:
        return {"navigatorItemId": {"guid": key}, "newName": new["name"]}
    if kind == "favorites":
        return {"oldName": key, "newName": new["name"]}
    if kind == "classification_systems":
        return {"classificationSystemId": {"guid": key}, **new}
    if kind == "classification_items":
        return {"classificationItemId": {"guid": key}, **new}
    if kind == "property_groups":
        return {"propertyGroupId": {"guid": key}, **new}
    if kind == "properties":
        return {"propertyId": {"guid": key}, **new}
    return {"attributeId": {"guid": key}, **new}


async def _plan(client, requests, port, operation):
    (request,) = requests
    port, target, _ = await write._context(client, port)
    rows = await _catalog(client, port, request)
    wanted = {r.old: r.new for r in request.renames or []}
    used = set()
    items = []
    for row in rows:
        new = {}
        for field, value in row["fields"].items():
            if request.find is not None:
                if request.find in value:
                    new[field] = value.replace(request.find, request.replace or "")
            elif value in wanted:
                used.add(value)
                new[field] = wanted[value]
        new = {k: v for k, v in new.items() if v != row["fields"][k]}
        if not new:
            continue
        if any(not v.strip() for v in new.values()):
            raise ValueError(f"{row['fields']} would get a blank name.")
        items.append(
            {
                "index": len(items),
                "status": "ready",
                "key": row["key"],
                "where": row["where"],
                "before": dict(row["fields"]),
                "after_name": {**row["fields"], **new},
                "parameters": _parameters(request.kind, row["key"], new),
            }
        )
    missing = [old for old in wanted if old not in used]
    if missing:
        raise ValueError(f"No {request.kind} named: {', '.join(map(repr, missing))}.")
    if not items:
        raise ValueError(f"No {request.kind} name contains {request.find!r}; nothing to rename.")
    if len(items) > MAX_RENAMES:
        raise ValueError(f"{len(items)} renames; at most {MAX_RENAMES} per call. Narrow it.")
    renamed = {i["key"] for i in items}
    final = [(row, row["fields"]) for row in rows if row["key"] not in renamed]
    final += [(next(r for r in rows if r["key"] == i["key"]), i["after_name"]) for i in items]
    seen: dict[tuple, str] = {}
    for row, fields in final:
        scope = _unique_scope(request.kind, row)
        field = "id" if request.kind == "classification_items" else "name"
        if scope is None or not fields.get(field):
            continue
        key = (scope, fields[field].casefold())
        if key in seen and seen[key] != row["key"]:
            raise ValueError(f"Two {request.kind} would be named {fields[field]!r}.")
        seen[key] = row["key"]
    return {"operation": operation, "kind": request.kind, "target": target, "items": items}


def _rows_of(raw: Any, key: str, count: int) -> list:
    rows = raw.get(key) if isinstance(raw, dict) else None
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueError("Unexpected rename response cardinality.")
    return rows


async def _send(client, receipt, items) -> None:
    """Send the renames; set each item to unverified, failed or unknown."""
    kind, port = receipt["kind"], receipt["target"]["port"]
    timeout = receipt["write_timeout_seconds"]
    batch = {
        "favorites": ("RenameFavorites", "renames", "executionResults"),
        "classification_systems": (
            "UpdateClassificationSystems",
            "classificationSystems",
            "executionResults",
        ),
        "classification_items": (
            "UpdateClassificationItems",
            "classificationItems",
            "executionResults",
        ),
        "property_groups": ("UpdatePropertyGroups", "propertyGroups", "executionResults"),
        "properties": ("UpdatePropertyDefinitions", "propertyDefinitions", "executionResults"),
    }
    if kind in NAVIGATOR:  # one item per call; stop at the first lost answer
        for position, item in enumerate(items):
            try:
                row = await client.tapir(
                    port, "RenameNavigatorItem", item["parameters"], timeout=timeout
                )
            except TapirError as exc:
                if exc.detail:
                    item.update(status="failed", error=exc.detail)
                    continue
                row, error = None, str(exc)
            except ArchicadError as exc:
                row, error = None, str(exc)
            if row is None:
                item.update(status="unknown", error=error)
                for rest in items[position + 1 :]:
                    rest.update(status="failed", error="Not sent after a lost answer.")
                receipt["warning"] = "Outcome unknown; inspect Archicad. Never retry this token."
                return
            item["write_response"] = row
            _outcome(item, row)
        return
    if kind in batch:
        command, list_key, answer_key = batch[kind]
        payload: dict = {list_key: [i["parameters"] for i in items]}
    else:
        _, command, list_key = ATTRIBUTES[kind]
        payload = {list_key: [i["parameters"] for i in items], "overwriteExisting": True}
        answer_key = "attributeIds"
    try:
        raw = await client.tapir(port, command, payload, timeout=timeout)
        rows = _rows_of(raw, answer_key, len(items))
    except TapirError as exc:
        for item in items:
            item.update(status="failed" if exc.detail else "unknown", error=exc.detail or str(exc))
        if not exc.detail:
            receipt["warning"] = "Outcome unknown; inspect Archicad. Never retry this token."
        return
    except (ArchicadError, ValueError) as exc:
        for item in items:
            item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Outcome unknown; inspect Archicad. Never retry this token."
        return
    for item, row in zip(items, rows, strict=True):
        item["write_response"] = row
        if answer_key == "attributeIds":
            same = isinstance(row, dict) and documents._guid(row.get("attributeId")) == item["key"]
            row = {"success": True} if same else {"success": False, "error": row}
        _outcome(item, row)


def _outcome(item: dict, row: Any) -> None:
    if isinstance(row, dict) and row.get("success") is True:
        item["status"] = "unverified"
    elif isinstance(row, dict) and row.get("success") is False:
        item.update(status="failed", error=row.get("error"))
    else:
        item.update(status="unknown", error="Unexpected rename result; inspect Archicad.")


async def _dispatch(client, receipt):
    items = receipt["items"]
    await _send(client, receipt, items)
    sent = [i for i in items if i["status"] == "unverified"]
    if not sent:
        return
    request = RenameRequest(kind=receipt["kind"], find="-", replace="")  # catalog scope only
    try:
        rows = await _catalog(
            client, receipt["target"]["port"], request, receipt["write_timeout_seconds"]
        )
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    by_key = {r["key"]: r["fields"] for r in rows}
    for item in sent:
        key = item["after_name"]["name"] if receipt["kind"] == "favorites" else item["key"]
        found = by_key.get(key)
        item["after"] = found
        problems = ["missing"] if found is None else []
        for field, wanted in item["after_name"].items():
            if found is not None and found.get(field) != wanted:
                problems.append(field)
        if receipt["kind"] == "favorites" and item["key"] in by_key:
            problems.append("old_name_still_exists")
        item["status"] = "verification_failed" if problems else "verified"
        if problems:
            item["mismatches"] = problems


async def rename_items(
    client: ArchicadClient,
    kind: str,
    renames: list[dict] | None = None,
    find: str | None = None,
    replace: str | None = None,
    scope: str | None = None,
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/apply renaming items of one kind, by find/replace or old -> new names."""
    request = RenameRequest.model_validate(
        {
            "kind": kind,
            **({"renames": renames} if renames is not None else {}),
            **({"find": find} if find is not None else {}),
            **({"replace": replace} if replace is not None else {}),
            **({"scope": scope} if scope is not None else {}),
        }
    )
    return await write._write(
        client,
        [request],
        port,
        dry_run,
        confirmation_token,
        "rename_items",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
