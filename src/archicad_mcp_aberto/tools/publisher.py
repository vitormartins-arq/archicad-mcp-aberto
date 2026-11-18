"""Publisher sets: read them, add or remove layouts, and publish a set or a selection.

A selection can be merged into one PDF, for example the floors of one house for a client.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from archicad_mcp_aberto.connection import ArchicadError, resolve_port
from archicad_mcp_aberto.tools import grids, write

GUID = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")
BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class PublishRequest(write.InputModel):
    publisher_set_name: str
    output_folder: str
    selected_item_guids: list[str] | None = None
    merged_pdf_name: str | None = None


class AddItemsRequest(write.InputModel):
    publisher_set_name: str
    layout_guids: list[str]
    parent_guid: str | None = None
    folder_name: str | None = None


class RemoveItemsRequest(write.InputModel):
    publisher_set_name: str
    item_guids: list[str]


def _folder(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute() or ".." in path.parts or any(c in value for c in "\x00\n\r"):
        raise ValueError("An absolute output folder is required.")
    if not path.is_dir():
        raise ValueError(f"Output folder does not exist: {path}")
    return path


def _guids(values: list[str], label: str) -> list[str]:
    if not values or any(not GUID.match(v) for v in values):
        raise ValueError(f"{label} must be a non-empty list of GUIDs.")
    upper = [v.upper() for v in values]
    if len(set(upper)) != len(upper):
        raise ValueError(f"{label} has repeated GUIDs.")
    return upper


def _pdf_name(value: str) -> str:
    name = value.strip()
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    if BAD_NAME.search(name) or name.startswith(".") or len(name) > 150:
        raise ValueError("merged_pdf_name must be a plain file name.")
    return name


def _files(folder: Path) -> dict:
    return {
        str(p.relative_to(folder)): p.stat().st_mtime_ns for p in folder.rglob("*") if p.is_file()
    }


async def _sets(client, port) -> list[dict]:
    raw = await grids._addon(client, port, "GetPublisherSets")
    sets = raw.get("sets") if isinstance(raw, dict) else None
    if not isinstance(sets, list):
        raise ValueError("Invalid publisher set list; update the companion add-on.")
    return sets


async def _set(client, port, name: str) -> dict:
    matches = [s for s in await _sets(client, port) if s.get("name") == name]
    if len(matches) != 1:
        raise ValueError(f"Publisher set not found or ambiguous: {name}")
    return matches[0]


async def _tree(client, port, map_id: str, set_name: str | None = None) -> dict:
    params = {"navigatorMapId": map_id}
    if set_name:
        params["publisherSetName"] = set_name
    raw = await client.tapir(port, "GetNavigatorItemTree", params)
    tree = raw.get("navigatorItemTree") if isinstance(raw, dict) else None
    if not isinstance(tree, dict):
        raise ValueError(f"Cannot read the {map_id} tree.")
    return tree


def _walk(node: dict, path: tuple = ()):
    for child in node.get("children") or []:
        item = child.get("navigatorItem") or {}
        guid = str((item.get("navigatorItemId") or {}).get("guid", "")).upper()
        label = " ".join(x for x in (item.get("uiId"), item.get("name")) if x)
        yield item, guid, path + (label,)
        yield from _walk(item, path + (label,))


def _row(item: dict, guid: str, path: tuple) -> dict:
    row = {"guid": guid, "type": item.get("type"), "id": item.get("uiId"), "name": item.get("name")}
    row["path"] = " / ".join(path)
    source = (item.get("sourceNavigatorItemId") or {}).get("guid")
    if source:
        row["layout_guid"] = str(source).upper()
    return row


async def list_publisher_sets(client, port: int | None = None) -> dict:
    port = await resolve_port(client, port)
    return {
        "port": port,
        "sets": await _sets(client, port),
        "note": "The Archicad API can read this saved output but has no call to change it.",
    }


async def get_publisher_set_items(client, publisher_set_name: str, port: int | None = None) -> dict:
    port = await resolve_port(client, port)
    root = await _set(client, port, publisher_set_name)
    tree = await _tree(client, port, "PublisherSets", publisher_set_name)
    return {
        "port": port,
        "publisher_set_name": publisher_set_name,
        "root_guid": root["rootGuid"],
        "items": [_row(*row) for row in _walk(tree)],
    }


async def list_layouts(client, name_contains: str | None = None, port: int | None = None) -> dict:
    """Layout Book layouts, optionally filtered by text in the ID, name or folder path."""
    port = await resolve_port(client, port)
    tree = await _tree(client, port, "LayoutBook")
    rows = [_row(*r) for r in _walk(tree) if r[0].get("type") == "LayoutItem"]
    if name_contains:
        needle = name_contains.casefold()
        rows = [r for r in rows if needle in r["path"].casefold()]
    return {"port": port, "layouts": rows}


# Publish ------------------------------------------------------------------------------


async def _publish_plan(client, requests, port, operation):
    (request,) = requests
    port = await resolve_port(client, port)
    folder = _folder(request.output_folder)
    root = await _set(client, port, request.publisher_set_name)
    item = {
        "index": 0,
        "status": "ready",
        "publisher_set_name": request.publisher_set_name,
        "root_guid": root["rootGuid"],
        "saved_path_before": root.get("path"),
        "output_folder": str(folder),
    }
    warnings = ["Publishing can replace same-named files in the output folder; no Undo."]
    if request.selected_item_guids is not None:
        selected = _guids(request.selected_item_guids, "selected_item_guids")
        tree = await _tree(client, port, "PublisherSets", request.publisher_set_name)
        known = {g: _row(i, g, p) for i, g, p in _walk(tree)}
        missing = [g for g in selected if g not in known]
        if missing:
            raise ValueError(f"Items not in this publisher set: {', '.join(missing)}")
        item["selected_items"] = [known[g] for g in selected]
    if request.merged_pdf_name is not None:
        if request.selected_item_guids is None:
            raise ValueError("merged_pdf_name needs selected_item_guids.")
        name = _pdf_name(request.merged_pdf_name)
        item["merged_pdf"] = str(folder / name)
        if (folder / name).exists():
            raise ValueError(f"{name} already exists in the output folder; pick another name.")
        warnings = [
            "Selected items publish to a temporary folder and are merged in the order given; "
            "only the merged PDF is written to the output folder."
        ]
    return {
        "operation": operation,
        "target": {"port": port},
        "items": [item],
        "warnings": warnings,
    }


def _merge(sources: list[Path], target: Path) -> int:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for source in sources:
        writer.append(str(source))
    pages = len(writer.pages)
    with open(target, "xb") as handle:
        writer.write(handle)
    return pages


async def _publish_dispatch(client, receipt):
    item = receipt["items"][0]
    port = receipt["target"]["port"]
    params = {"rootGuid": item["root_guid"]}
    if item.get("selected_items"):
        params["selectedItemGuids"] = [r["guid"] for r in item["selected_items"]]
    merge = item.get("merged_pdf")
    temp = Path(tempfile.mkdtemp(prefix="archicad-publish-")) if merge else None
    try:
        folder = _folder(item["output_folder"])
        destination = temp or folder
        before = _files(destination)
        params["outputPath"] = str(destination)
        response = await grids._addon(
            client, port, "PublishPublisherSet", params, receipt["write_timeout_seconds"]
        )
        if isinstance(response, dict) and response.get("error"):
            raise ValueError(str(response["error"].get("message", response["error"])))
        after = _files(destination)
        written = sorted(n for n, t in after.items() if before.get(n) != t)
        if merge:
            pdfs = [n for n in written if n.lower().endswith(".pdf")]
            if not pdfs:
                raise ValueError("Archicad wrote no PDF for the selection.")
            # Archicad names each file "<ID> <name>.pdf"; follow the requested item order
            # and keep the ID order for multi-page layouts.
            order = {r["id"] or "": i for i, r in enumerate(item["selected_items"])}

            def key(name):
                hit = [i for k, i in order.items() if k and Path(name).name.startswith(k)]
                return (min(hit) if hit else len(order), name)

            pdfs.sort(key=key)
            item["merged_from"] = pdfs
            item["merged_pages"] = _merge([destination / n for n in pdfs], Path(merge))
            item["files_written"] = [Path(merge).name]
        else:
            item["files_written"] = written
    except (ValueError, OSError) as exc:
        item.update(status="failed", error=str(exc))
        return
    except ArchicadError as exc:
        item.update(status="unknown", error=str(exc))
        receipt["warning"] = "Publish outcome unknown. Inspect the folder; never retry this token."
        return
    finally:
        if temp is not None:
            shutil.rmtree(temp, ignore_errors=True)
    try:
        rows = await _sets(client, port)
        item["saved_path_after"] = next(
            s.get("path") for s in rows if s.get("rootGuid") == item["root_guid"]
        )
    except (ArchicadError, ValueError, StopIteration) as exc:
        item["saved_path_after_error"] = str(exc)
    item["status"] = "verified" if item["files_written"] else "unverified"


async def publish_publisher_set(
    client,
    publisher_set_name: str,
    output_folder: str,
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
    selected_item_guids: list[str] | None = None,
    merged_pdf_name: str | None = None,
):
    return await write._write(
        client,
        [
            PublishRequest(
                publisher_set_name=publisher_set_name,
                output_folder=output_folder,
                selected_item_guids=selected_item_guids,
                merged_pdf_name=merged_pdf_name,
            )
        ],
        port,
        dry_run,
        confirmation_token,
        "publish_publisher_set",
        planner_override=_publish_plan,
        dispatcher_override=_publish_dispatch,
        completion_note="Check files_written and saved_path_after; publishing has no Undo.",
    )


# Save layouts as PDF ------------------------------------------------------------------


class SaveLayoutsRequest(write.InputModel):
    layout_guids: list[str]
    output_folder: str
    merged_pdf_name: str


async def _save_plan(client, requests, port, operation):
    (request,) = requests
    port = await resolve_port(client, port)
    folder = _folder(request.output_folder)
    guids = _guids(request.layout_guids, "layout_guids")
    layouts = {r["guid"]: r for r in (await list_layouts(client, None, port))["layouts"]}
    missing = [g for g in guids if g not in layouts]
    if missing:
        raise ValueError(f"Not Layout Book layouts: {', '.join(missing)}")
    name = _pdf_name(request.merged_pdf_name)
    if (folder / name).exists():
        raise ValueError(f"{name} already exists in the output folder; pick another name.")
    return {
        "operation": operation,
        "target": {"port": port},
        "items": [
            {
                "index": 0,
                "status": "ready",
                "layouts": [layouts[g] for g in guids],
                "output_folder": str(folder),
                "merged_pdf": str(folder / name),
            }
        ],
        "warnings": [
            "Opens each layout window, saves it as PDF to a temporary folder and merges the "
            "pages in the order given. Only the merged PDF is written; the Publisher is untouched."
        ],
    }


async def _save_dispatch(client, receipt):
    item = receipt["items"][0]
    port = receipt["target"]["port"]
    temp = Path(tempfile.mkdtemp(prefix="archicad-layout-pdf-"))
    try:
        response = await grids._addon(
            client,
            port,
            "SaveLayoutsAsPdf",
            {"outputPath": str(temp), "layoutGuids": [r["guid"] for r in item["layouts"]]},
            receipt["write_timeout_seconds"],
        )
        files = [f.get("file") for f in response.get("files") or []]
        if len(files) != len(item["layouts"]) or not all(files):
            raise ValueError("Archicad did not save every layout as PDF.")
        item["merged_from"] = files
        item["merged_pages"] = _merge([temp / f for f in files], Path(item["merged_pdf"]))
        item["files_written"] = [Path(item["merged_pdf"]).name]
        item["status"] = "verified"
    except (ValueError, OSError) as exc:
        item.update(status="failed", error=str(exc))
    except ArchicadError as exc:
        item.update(status="unknown", error=str(exc))
        receipt["warning"] = (
            "Outcome unknown. Check Archicad and the folder; never retry this token."
        )
    finally:
        shutil.rmtree(temp, ignore_errors=True)


async def save_layouts_as_pdf(
    client,
    layout_guids: list[str],
    output_folder: str,
    merged_pdf_name: str,
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
):
    return await write._write(
        client,
        [
            SaveLayoutsRequest(
                layout_guids=layout_guids,
                output_folder=output_folder,
                merged_pdf_name=merged_pdf_name,
            )
        ],
        port,
        dry_run,
        confirmation_token,
        "save_layouts_as_pdf",
        planner_override=_save_plan,
        dispatcher_override=_save_dispatch,
        completion_note="Only the merged PDF was written; no project was saved.",
    )
