"""Tables built from the model itself, written as XLSX, and checks of the data behind them.

Archicad 30 lets no API configure or read an Interactive Schedule. The data that feeds
one is open, though: element types, properties, classifications and GDL parameters.
`export_model_table` reads that data with a table definition (columns, filters,
grouping, totals) and writes a formatted XLSX. `check_table_data` uses the same
definition to list the elements whose values are missing, which is what usually makes a
schedule wrong. Both only read the model; the export writes one new file and never
overwrites.

Column sources:
- ``guid``, ``type``                        element GUID and element type;
- ``builtin:<nonLocalizedName>``            built-in property, e.g. builtin:General_ElementID;
- ``prop:<Group>/<Name>``                   user-defined property;
- ``class:<System name>``                   classification "ID Name" in that system;
- ``param:<GDL name>``                      GDL parameter of Objects and Lamps (needs Tapir).
"""

from __future__ import annotations

import json
import math
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from xml.sax.saxutils import escape

from pydantic import Field

from archicad_mcp_aberto.connection import ArchicadClient, resolve_port
from archicad_mcp_aberto.tools import classifications, write

BATCH = 100
BAD_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
SOURCE = re.compile(r"^(guid|type|builtin:.+|prop:[^/]+/.+|class:.+|param:.+)$")


class Column(write.InputModel):
    header: str = Field(min_length=1, max_length=80)
    source: str = Field(min_length=1, max_length=255)
    required: bool = False


class Filter(write.InputModel):
    column: str
    operator: Literal["equal", "not_equal", "contains", "empty", "not_empty"] = "equal"
    value: str | float | int | bool | None = None


class TableDefinition(write.InputModel):
    name: str = Field(min_length=1, max_length=80)
    element_types: list[str] = Field(min_length=1, max_length=20)
    columns: list[Column] = Field(min_length=1, max_length=40)
    filters: list[Filter] = Field(default_factory=list, max_length=20)
    group_by: list[str] = Field(default_factory=list, max_length=5)
    sum_columns: list[str] = Field(default_factory=list, max_length=20)
    sort_by: list[str] = Field(default_factory=list, max_length=5)


def _definition(definition: dict | TableDefinition | None, path: str | None) -> TableDefinition:
    if (definition is None) == (path is None):
        raise ValueError("Pass either definition or definition_path.")
    if path is not None:
        file = Path(path)
        if not file.is_absolute() or file.suffix.lower() != ".json" or not file.is_file():
            raise ValueError("definition_path must be an existing absolute .json file.")
        definition = json.loads(file.read_text(encoding="utf-8"))
    table = (
        definition
        if isinstance(definition, TableDefinition)
        else TableDefinition.model_validate(definition)
    )
    headers = [c.header for c in table.columns]
    if len(set(headers)) != len(headers):
        raise ValueError("Column headers must be unique.")
    for column in table.columns:
        if not SOURCE.match(column.source):
            raise ValueError(f"Unknown column source: {column.source!r}.")
    named = [f.column for f in table.filters] + table.group_by + table.sum_columns + table.sort_by
    unknown = sorted({h for h in named if h not in headers})
    if unknown:
        raise ValueError(f"Unknown column headers: {', '.join(unknown)}.")
    for f in table.filters:
        if f.operator in {"equal", "not_equal", "contains"} and f.value is None:
            raise ValueError(f"Filter on {f.column!r} needs a value.")
    return table


def _chunks(rows: list, size: int = BATCH):
    for start in range(0, len(rows), size):
        yield rows[start : start + size]


def _plain(value: Any) -> Any:
    """Property value -> cell value; None when empty, unavailable or an error."""
    if not isinstance(value, dict) or value.get("status", "normal") != "normal":
        return None
    raw = value.get("value")
    if isinstance(raw, list):
        parts = [str(v.get("displayValue", v) if isinstance(v, dict) else v) for v in raw]
        raw = ", ".join(p for p in parts if p)
    elif isinstance(raw, dict):
        raw = raw.get("displayValue") or raw.get("nonLocalizedValue")
    if isinstance(raw, float) and not math.isfinite(raw):
        return None
    if raw == "":
        return None
    return raw


async def _elements(client: ArchicadClient, port: int, kinds: list[str]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for kind in kinds:
        rows = (await client.command(port, "GetElementsByType", {"elementType": kind})).get(
            "elements", []
        )
        for row in rows:
            guid = str(row["elementId"]["guid"]).upper()
            if guid not in seen:
                seen.add(guid)
                out.append((guid, kind))
    return out


async def _property_ids(client, port, columns: list[Column]) -> tuple[dict, list[str]]:
    wanted = []
    for column in columns:
        kind, _, rest = column.source.partition(":")
        if kind == "builtin":
            wanted.append((column.header, {"type": "BuiltIn", "nonLocalizedName": rest}))
        elif kind == "prop":
            group, _, name = rest.partition("/")
            wanted.append(
                (
                    column.header,
                    {"type": "UserDefined", "localizedName": [group.strip(), name.strip()]},
                )
            )
    if not wanted:
        return {}, []
    rows = (
        await client.command(port, "GetPropertyIds", {"properties": [w[1] for w in wanted]})
    ).get("properties", [])
    found, missing = {}, []
    for (header, _), row in zip(wanted, rows, strict=False):
        guid = (row.get("propertyId") or {}).get("guid") if isinstance(row, dict) else None
        if guid:
            found[header] = guid
        else:
            missing.append(header)
    return found, missing


async def _properties(client, port, guids: list[str], ids: dict[str, str]) -> dict:
    values: dict[str, dict[str, Any]] = {g: {} for g in guids}
    if not ids:
        return values
    headers = list(ids)
    properties = [{"propertyId": {"guid": ids[h]}} for h in headers]
    for chunk in _chunks(guids):
        result = await client.command(
            port,
            "GetPropertyValuesOfElements",
            {"elements": [{"elementId": {"guid": g}} for g in chunk], "properties": properties},
        )
        for guid, row in zip(chunk, result.get("propertyValuesForElements", []), strict=False):
            for header, cell in zip(headers, row.get("propertyValues") or [], strict=False):
                values[guid][header] = _plain(cell.get("propertyValue"))
    return values


async def _classifications(client, port, guids: list[str], columns: list[Column]) -> tuple:
    wanted = [c for c in columns if c.source.startswith("class:")]
    values: dict[str, dict[str, Any]] = {g: {} for g in guids}
    if not wanted:
        return values, []
    systems = await classifications._systems(client, port)
    picked, missing = {}, []
    for column in wanted:
        try:
            picked[column.header] = classifications._pick_system(systems, column.source[6:])
        except ValueError:
            missing.append(column.header)
    labels: dict[str, str] = {}
    for system in {s["guid"] for s in picked.values()}:
        for item in await classifications._items(client, port, system):
            labels[item["guid"]] = " ".join(x for x in (item.get("id"), item.get("name")) if x)
    headers = list(picked)
    ids = [{"classificationSystemId": {"guid": picked[h]["guid"]}} for h in headers]
    for chunk in _chunks(guids):
        result = await client.command(
            port,
            "GetClassificationsOfElements",
            {
                "elements": [{"elementId": {"guid": g}} for g in chunk],
                "classificationSystemIds": ids,
            },
        )
        for guid, row in zip(chunk, result.get("elementClassifications", []), strict=False):
            for header, cell in zip(headers, row.get("classificationIds") or [], strict=False):
                item = ((cell.get("classificationId") or {}).get("classificationItemId")) or {}
                guid_item = str(item.get("guid", "")).upper()
                values[guid][header] = labels.get(guid_item) if guid_item else None
    return values, missing


async def _parameters(client, port, elements, columns: list[Column]) -> dict:
    wanted = {c.header: c.source[6:] for c in columns if c.source.startswith("param:")}
    values: dict[str, dict[str, Any]] = {g: {} for g, _ in elements}
    targets = [g for g, kind in elements if kind in {"Object", "Lamp"}]
    if not wanted or not targets:
        return values
    for chunk in _chunks(targets):
        result = await client.tapir(
            port,
            "GetGDLParametersOfElements",
            {"elements": [{"elementId": {"guid": g}} for g in chunk]},
        )
        for guid, row in zip(chunk, result.get("gdlParametersOfElements", []), strict=False):
            by_name = {
                p.get("name"): p.get("value")
                for p in (row.get("parameters") or [] if isinstance(row, dict) else [])
                if isinstance(p, dict)
            }
            for header, name in wanted.items():
                value = by_name.get(name)
                values[guid][header] = None if value in ("", None) else value
    return values


def _matches(value: Any, f: Filter) -> bool:
    if f.operator == "empty":
        return value is None
    if f.operator == "not_empty":
        return value is not None
    if value is None:
        return f.operator == "not_equal"
    if f.operator == "contains":
        return str(f.value).casefold() in str(value).casefold()
    same = value == f.value or str(value).casefold() == str(f.value).casefold()
    return same if f.operator == "equal" else not same


async def _collect(client, port, table: TableDefinition) -> dict:
    elements = await _elements(client, port, table.element_types)
    guids = [g for g, _ in elements]
    ids, missing_props = await _property_ids(client, port, table.columns)
    props = await _properties(client, port, guids, ids)
    classes, missing_systems = await _classifications(client, port, guids, table.columns)
    params = await _parameters(client, port, elements, table.columns)
    rows = []
    for guid, kind in elements:
        row = {}
        for column in table.columns:
            source = column.source
            if source == "guid":
                row[column.header] = guid
            elif source == "type":
                row[column.header] = kind
            else:
                row[column.header] = (
                    props[guid].get(column.header)
                    if source.startswith(("builtin:", "prop:"))
                    else classes[guid].get(column.header)
                    if source.startswith("class:")
                    else params[guid].get(column.header)
                )
        rows.append({"guid": guid, "values": row})
    kept = [r for r in rows if all(_matches(r["values"][f.column], f) for f in table.filters)]
    unresolved = [
        *({"column": h, "reason": "property not found"} for h in missing_props),
        *({"column": h, "reason": "classification system not found"} for h in missing_systems),
    ]
    return {"elements": len(elements), "rows": kept, "unresolved": unresolved}


def _sort_key(value: Any):
    if value is None:
        return (2, "")
    if isinstance(value, bool):
        return (1, str(value))
    if isinstance(value, (int, float)):
        return (0, value)
    return (1, str(value).casefold())


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _label(value: Any) -> Any:
    return "(sem valor)" if value is None else value


def _summary(table: TableDefinition, rows: list[dict]) -> list[dict]:
    groups: dict[tuple, dict] = {}
    for row in rows:
        key = tuple(row["values"][h] for h in table.group_by)
        group = groups.setdefault(key, {"count": 0, **{h: 0.0 for h in table.sum_columns}})
        group["count"] += 1
        for header in table.sum_columns:
            group[header] += _number(row["values"][header]) or 0.0
    out = []
    for key in sorted(groups, key=lambda k: tuple(_sort_key(v) for v in k)):
        out.append({**dict(zip(table.group_by, key, strict=True)), **groups[key]})
    return out


# Minimal XLSX writer: inline strings, numbers, bold header, frozen first row, filter.


def _col(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def _cell(ref: str, value: Any, style: int = 0) -> str:
    s = f' s="{style}"' if style else ""
    if value is None:
        return f'<c r="{ref}"{s}/>'
    if isinstance(value, bool):
        value = "Sim" if value else "Não"
    if isinstance(value, (int, float)) and math.isfinite(value):
        return f'<c r="{ref}"{s}><v>{value!r}</v></c>'
    text = escape(str(value)).replace("\n", "&#10;")
    return f'<c r="{ref}"{s} t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _sheet(headers: list[str], rows: list[list[Any]]) -> str:
    widths = [
        min(60, max(10, len(str(h)) + 2, *(len(str(r[i] or "")) + 2 for r in rows)))
        for i, h in enumerate(headers)
    ]
    cols = "".join(
        f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
        for i, w in enumerate(widths)
    )
    lines = [
        '<row r="1">'
        + "".join(_cell(f"{_col(i)}1", h, 1) for i, h in enumerate(headers))
        + "</row>"
    ]
    for n, row in enumerate(rows, start=2):
        lines.append(
            f'<row r="{n}">'
            + "".join(_cell(f"{_col(i)}{n}", v) for i, v in enumerate(row))
            + "</row>"
        )
    last = f"{_col(len(headers) - 1)}{len(rows) + 1}"
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f"<cols>{cols}</cols><sheetData>{''.join(lines)}</sheetData>"
        f'<autoFilter ref="A1:{last}"/></worksheet>'
    )


def _write_xlsx(path: Path, sheets: list[tuple[str, list[str], list[list[Any]]]]) -> None:
    names = [escape(n[:31]) for n, _, _ in sheets]
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
        + "".join(
            f'<sheet name="{n}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, n in enumerate(names)
        )
        + "</sheets></workbook>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{i + 1}" Type="http://schemas.openxmlformats.org/'
            f'officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
            for i in range(len(sheets))
        )
        + f'<Relationship Id="rId{len(sheets) + 1}" Type="http://schemas.openxmlformats.org/'
        'officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="3"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFE7E6E6"/></patternFill></fill>'
        "</fills>"
        '<borders count="1"><border/></borders><cellStyleXfs count="1"><xf/></cellStyleXfs>'
        '<cellXfs count="2"><xf/><xf fontId="1" fillId="2" applyFont="1" applyFill="1"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )
    types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/'
        'vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
        'officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-'
        'officedocument.spreadsheetml.styles+xml"/>'
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(len(sheets))
        )
        + "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>'
    )
    with open(path, "xb") as handle, zipfile.ZipFile(handle, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", types)
        z.writestr("_rels/.rels", root_rels)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", rels)
        z.writestr("xl/styles.xml", styles)
        for i, (_, headers, rows) in enumerate(sheets):
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", _sheet(headers, rows))


def _missing(table: TableDefinition, rows: list[dict]) -> list[dict]:
    required = [c.header for c in table.columns if c.required]
    out = []
    for row in rows:
        empty = [h for h in required if row["values"][h] is None]
        if empty:
            out.append({"guid": row["guid"], "missing": empty, "values": row["values"]})
    return out


async def check_table_data(
    client: ArchicadClient,
    definition: dict | None = None,
    definition_path: str | None = None,
    port: int | None = None,
    limit: int = 100,
) -> dict:
    """List elements of a table whose required columns are empty. Read-only."""
    table = _definition(definition, definition_path)
    port = await resolve_port(client, port)
    data = await _collect(client, port, table)
    problems = _missing(table, data["rows"])
    per_column: dict[str, int] = {}
    for p in problems:
        for header in p["missing"]:
            per_column[header] = per_column.get(header, 0) + 1
    return {
        "port": port,
        "table": table.name,
        "elements_read": data["elements"],
        "rows": len(data["rows"]),
        "rows_with_missing_values": len(problems),
        "missing_by_column": per_column,
        "unresolved_columns": data["unresolved"],
        "problems": problems[: max(0, min(limit, 500))],
        "note": "Mark columns required=true to check them. Select a GUID with select_elements.",
    }


async def export_model_table(
    client: ArchicadClient,
    output_folder: str,
    definition: dict | None = None,
    definition_path: str | None = None,
    port: int | None = None,
    file_name: str | None = None,
) -> dict:
    """Read the model with a table definition and write one new XLSX. Model untouched."""
    table = _definition(definition, definition_path)
    folder = Path(output_folder)
    if not folder.is_absolute() or not folder.is_dir():
        raise ValueError("output_folder must be an existing absolute folder.")
    name = (file_name or f"{table.name} {datetime.now():%Y-%m-%d %H%M}").strip()
    if not name.lower().endswith(".xlsx"):
        name += ".xlsx"
    if BAD_NAME.search(name) or name.startswith(".") or len(name) > 150:
        raise ValueError("file_name must be a plain file name.")
    target = folder / name
    if target.exists() and file_name:
        raise ValueError(f"{name} already exists; pick another name.")
    copy = 2
    while target.exists():  # automatic names get a counter instead of overwriting
        target = folder / f"{name[:-5]} ({copy}).xlsx"
        copy += 1
    port = await resolve_port(client, port)
    data = await _collect(client, port, table)
    rows = data["rows"]
    if table.sort_by:
        rows = sorted(rows, key=lambda r: tuple(_sort_key(r["values"][h]) for h in table.sort_by))
    headers = [c.header for c in table.columns]
    sheets = [(table.name, headers, [[r["values"][h] for h in headers] for r in rows])]
    summary = []
    if table.group_by:
        summary = _summary(table, rows)
        summary_headers = [*table.group_by, "Quantidade", *table.sum_columns]
        sheets.append(
            (
                "Resumo",
                summary_headers,
                [
                    [
                        *(_label(s[h]) for h in table.group_by),
                        s["count"],
                        *(s[h] for h in table.sum_columns),
                    ]
                    for s in summary
                ],
            )
        )
    problems = _missing(table, rows)
    if problems:
        sheets.append(
            (
                "Pendências",
                ["GUID", "Campos vazios", *headers],
                [
                    [p["guid"], ", ".join(p["missing"]), *(p["values"][h] for h in headers)]
                    for p in problems
                ],
            )
        )
    _write_xlsx(target, sheets)
    return {
        "port": port,
        "file": str(target),
        "table": table.name,
        "elements_read": data["elements"],
        "rows": len(rows),
        "groups": len(summary),
        "rows_with_missing_values": len(problems),
        "unresolved_columns": data["unresolved"],
        "sheets": [s[0] for s in sheets],
    }
