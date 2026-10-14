"""Rename template items in bulk (Tapir 1.7.0), for cleaning up an office template.

One call renames one kind of item, either by find and replace on the names or by a list
of exact old -> new names. Kinds: Navigator items (View Map, Project Map, Layout Book),
favorites, classification systems and items, custom property groups and properties,
building materials, layers, layer combinations, and attribute folders (the
folders of the layer, material, surface... dialogs; official JSON API). Every item keeps
its GUID, so elements that use it follow the new name. A renamed layer combination keeps
every layer's state, which is read back. Renamed View Map items get a custom name, as in
Archicad. Model View Options and Graphic Overrides have no Tapir 1.7.0 command, so they
are not here.
Uses the shared preview, single-use token and receipts, and reads every name back.
Never saves.
"""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import Field, model_validator

from archicad_mcp_aberto.connection import (
    ArchicadClient,
    ArchicadError,
    CommandFailed,
    TapirError,
)
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
    "layers": ("Layer", "CreateLayers", "layerDataArray"),
    # Tapir 1.7.0 requires "layers" and seeds an overwritten combination from its own layer
    # table, so a name plus an empty list keeps every layer's state; _layer_states checks it.
    "layer_combinations": (
        "LayerCombination",
        "CreateLayerCombinations",
        "layerCombinationDataArray",
    ),
}
# Attribute types with folders (official JSON API, AC27+), for kind attribute_folders.
FOLDER_TYPES = (
    "Layer", "LayerCombination", "BuildingMaterial", "Surface", "Composite", "Fill", "Line",
    "PenTable", "Profile", "ZoneCategory", "MEPSystem", "OperationProfile",
)  # fmt: skip
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
    "layer_combinations",
    "attribute_folders",
]


# Live AC30 build 3001 BRA, Tapir 1.7.0 (14/10/2026): CreateSurfaces with overwriteExisting
# and only the name renamed the surface but also changed its texture, so surfaces are refused.
SURFACES_REFUSED = (
    "Renaming surfaces is turned off: in the live test of 14/10/2026 Tapir 1.7.0 also "
    "changed the texture of every renamed surface. Rename them by hand in Archicad for now."
)


class Rename(write.InputModel):
    old: Text
    new: Text


class RenameRequest(write.InputModel):
    kind: Kind
    renames: Annotated[list[Rename], Field(min_length=1, max_length=MAX_RENAMES)] | None = None
    find: Text | None = None
    replace: Annotated[str, Field(max_length=255)] | None = None
    # classification system, property group, favorite type or folder attribute type
    scope: Text | None = None

    @model_validator(mode="after")
    def one_way(self):
        if self.kind == "surfaces":
            raise ValueError(SURFACES_REFUSED)
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
        if self.kind == "attribute_folders":
            if self.scope is None:
                raise ValueError(
                    f"attribute_folders needs scope, the attribute type: {', '.join(FOLDER_TYPES)}."
                )
            folder_type = next(
                (t for t in FOLDER_TYPES if t.casefold() == self.scope.casefold()), None
            )
            if folder_type is None:
                raise ValueError(f"Unknown folder attribute type {self.scope!r}.")
            self.scope = folder_type
        elif self.scope is not None and self.kind not in (
            "classification_items",
            "properties",
            "favorites",
        ):
            raise ValueError(
                "scope is only for classification_items, properties, favorites and "
                "attribute_folders."
            )
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


def _folder_rows(node: Any, depth: int, path: str, out: list[dict]) -> list[dict]:
    if not isinstance(node, dict):
        return out
    guid = documents._guid(node.get("attributeFolderId"))
    name = node.get("name")
    if guid and depth > 0 and isinstance(name, str):  # the root folder is not renamed
        out.append({"key": guid, "fields": {"name": name}, "where": path})
    subfolders = node.get("subfolders") if isinstance(node.get("subfolders"), list) else []
    for child in subfolders:
        folder = child.get("attributeFolder") if isinstance(child, dict) else None
        _folder_rows(folder, depth + 1, f"{path}/{name}" if depth > 0 else "", out)
    return out


async def _layer_states(client, port, keys: list[str], timeout=None) -> dict[str, str]:
    """Combination GUID -> digest of its layers' states (hidden, locked, wire, group)."""
    if not keys:
        return {}
    extra = {} if timeout is None else {"timeout": timeout}
    raw = await client.tapir(
        port,
        "GetLayerCombinations",
        {"attributes": [{"attributeId": {"guid": k}} for k in keys]},
        **extra,
    )
    rows = _rows_of(raw, "layerCombinations", len(keys))
    out = {}
    for key, row in zip(keys, rows, strict=True):
        combination = row.get("layerCombination") if isinstance(row, dict) else None
        layers = combination.get("layers") if isinstance(combination, dict) else None
        if not isinstance(layers, list):
            raise ValueError(f"Could not read the layers of layer combination {key}.")
        states = sorted(
            json.dumps(
                {
                    "layer": documents._guid(layer.get("attributeId")),
                    **{
                        f: layer.get(f)
                        for f in ("isHidden", "isLocked", "isWireframe", "intersectionGroupNr")
                    },
                },
                sort_keys=True,
            )
            for layer in layers
            if isinstance(layer, dict)
        )
        out[key] = hashlib.sha256("\n".join(states).encode()).hexdigest()
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
    if kind == "attribute_folders":
        response = await client.command(
            port, "GetAttributeFolderStructure", {"attributeType": request.scope}, **extra
        )
        root = response.get("attributeFolder")
        if not isinstance(root, dict):
            raise ValueError(f"Unexpected {request.scope} folder structure response.")
        return _folder_rows(root, 0, "", [])
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
    if kind in ("classification_items", "properties", "attribute_folders"):
        return str(row["where"])  # within a system, a group or a parent folder
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
    if kind == "attribute_folders":
        return {"attributeFolderId": {"guid": key}, "newName": new["name"]}
    if kind == "layer_combinations":
        return {"attributeId": {"guid": key}, **new, "layers": []}
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
        if request.kind == "attribute_folders" and new["name"] != new["name"].strip():
            raise ValueError(f"Folder name {new['name']!r} must not start or end with a space.")
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
    if request.kind == "layer_combinations":
        states = await _layer_states(client, port, [i["key"] for i in items])
        for item in items:
            item["layer_states"] = states[item["key"]]
    plan = {"operation": operation, "kind": request.kind, "target": target, "items": items}
    if request.scope is not None:
        plan["scope"] = request.scope
    return plan


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
            except CommandFailed as exc:  # Archicad refused the call (e.g. schema check)
                item.update(status="failed", error=exc.detail or str(exc))
                continue
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
    if kind == "attribute_folders":  # official JSON API: a refused call raises CommandFailed
        try:
            raw = await client.command(
                port,
                "RenameAttributeFolders",
                {"attributeFolderParametersList": [i["parameters"] for i in items]},
                timeout=timeout,
            )
            rows = _rows_of(raw, "executionResults", len(items))
        except CommandFailed as exc:
            for item in items:
                item.update(status="failed", error=exc.detail or str(exc))
            return
        except (ArchicadError, ValueError) as exc:
            for item in items:
                item.update(status="unknown", error=str(exc))
            receipt["warning"] = "Outcome unknown; inspect Archicad. Never retry this token."
            return
        for item, row in zip(items, rows, strict=True):
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
    except CommandFailed as exc:  # Archicad refused the call before running it
        for item in items:
            item.update(status="failed", error=exc.detail or str(exc))
        return
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
    # catalog scope only; find/replace are placeholders
    request = RenameRequest(kind=receipt["kind"], find="-", replace="", scope=receipt.get("scope"))
    port, timeout = receipt["target"]["port"], receipt["write_timeout_seconds"]
    try:
        rows = await _catalog(client, port, request, timeout)
        states = {}
        if receipt["kind"] == "layer_combinations":
            states = await _layer_states(client, port, [i["key"] for i in sent], timeout)
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
        if "layer_states" in item and states.get(item["key"]) != item["layer_states"]:
            problems.append("layer_states")
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
