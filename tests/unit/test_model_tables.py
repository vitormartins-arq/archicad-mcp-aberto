"""export_model_table / check_table_data against the fake Archicad; XLSX read back."""

import re
import zipfile

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import model_tables
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio

L1, L2, L3, W1 = (f"00000000-0000-4000-8000-00000000000{i}" for i in range(1, 5))
ID, POWER, ROOM = (f"10000000-0000-4000-8000-00000000000{i}" for i in range(1, 4))
SYSTEM = "1C4E9A10-3B7F-4D2A-9E61-0A5B7C3D2E11"
WALL_ITEM = "A1000000-0000-4000-8000-000000000001"


def value(v):
    return {"type": "string", "status": "normal", "value": v}


def fake():
    f = FakeArchicad(19723)
    f.elements.update({L1: "Lamp", L2: "Lamp", L3: "Lamp", W1: "Wall"})
    f.builtin_property_ids["General_ElementID"] = ID
    f.user_property_ids[("LAB", "Potência")] = POWER
    f.user_property_ids[("LAB", "Ambiente")] = ROOM
    for guid, eid, power, room in (
        (L1, "L-01", 10.0, "Sala"),
        (L2, "L-02", 7.5, "Sala"),
        (L3, "L-03", 4.0, None),
    ):
        f.property_values[(guid, ID)] = value(eid)
        f.property_values[(guid, POWER)] = {"type": "number", "status": "normal", "value": power}
        f.property_values[(guid, ROOM)] = (
            value(room) if room else {"type": "string", "status": "normal", "value": ""}
        )
    f.classifications[(L1, SYSTEM)] = WALL_ITEM
    return f


DEFINITION = {
    "name": "Luminárias",
    "element_types": ["Lamp"],
    "columns": [
        {"header": "ID", "source": "builtin:General_ElementID"},
        {"header": "Ambiente", "source": "prop:LAB/Ambiente", "required": True},
        {"header": "Potência", "source": "prop:LAB/Potência"},
        {"header": "Classe", "source": "class:ARCHICAD Classification"},
        {"header": "Largura", "source": "param:A"},
    ],
    "group_by": ["Ambiente"],
    "sum_columns": ["Potência"],
    "sort_by": ["ID"],
}


def sheet_text(path, index):
    with zipfile.ZipFile(path) as z:
        xml = z.read(f"xl/worksheets/sheet{index}.xml").decode()
    return re.findall(r"<t xml:space=\"preserve\">([^<]*)</t>|<v>([^<]*)</v>", xml)


async def test_export_writes_rows_summary_and_pending(tmp_path):
    f = fake()
    async with ArchicadClient(transport=fake_transport(f)) as c:
        result = await model_tables.export_model_table(
            c, str(tmp_path), DEFINITION, port=19723, file_name="lum"
        )
    assert result["rows"] == 3 and result["elements_read"] == 3
    assert result["sheets"] == ["Luminárias", "Resumo", "Pendências"]
    assert result["rows_with_missing_values"] == 1 and result["unresolved_columns"] == []
    path = tmp_path / "lum.xlsx"
    assert result["file"] == str(path)
    cells = [a or b for a, b in sheet_text(path, 1)]
    assert cells[:5] == ["ID", "Ambiente", "Potência", "Classe", "Largura"]
    assert cells[5:10] == ["L-01", "Sala", "10.0", "Parede Parede", "1.0"]
    summary = [a or b for a, b in sheet_text(path, 2)]
    assert summary == [
        "Ambiente",
        "Quantidade",
        "Potência",
        "Sala",
        "2",
        "17.5",
        "(sem valor)",
        "1",
        "4.0",
    ]
    pending = [a or b for a, b in sheet_text(path, 3)]
    assert L3 in pending and "Ambiente" in pending


async def test_export_never_overwrites(tmp_path):
    (tmp_path / "lum.xlsx").write_bytes(b"old")
    async with ArchicadClient(transport=fake_transport(fake())) as c:
        with pytest.raises(ValueError, match="already exists"):
            await model_tables.export_model_table(
                c, str(tmp_path), DEFINITION, port=19723, file_name="lum.xlsx"
            )
    assert (tmp_path / "lum.xlsx").read_bytes() == b"old"


async def test_filters_and_check_table_data():
    definition = {
        **DEFINITION,
        "filters": [{"column": "Potência", "operator": "not_equal", "value": 4.0}],
    }
    async with ArchicadClient(transport=fake_transport(fake())) as c:
        clean = await model_tables.check_table_data(c, definition, port=19723)
        everything = await model_tables.check_table_data(c, DEFINITION, port=19723)
    assert clean["rows"] == 2 and clean["rows_with_missing_values"] == 0
    assert everything["missing_by_column"] == {"Ambiente": 1}
    assert everything["problems"][0]["guid"] == L3


async def test_unknown_property_is_reported_not_invented():
    definition = {
        **DEFINITION,
        "columns": [*DEFINITION["columns"], {"header": "X", "source": "prop:LAB/Nada"}],
    }
    async with ArchicadClient(transport=fake_transport(fake())) as c:
        result = await model_tables.check_table_data(c, definition, port=19723)
    assert result["unresolved_columns"] == [{"column": "X", "reason": "property not found"}]


@pytest.mark.parametrize(
    "change, message",
    [
        ({"group_by": ["Nada"]}, "Unknown column headers"),
        ({"columns": [{"header": "A", "source": "xyz"}]}, "Unknown column source"),
        ({"filters": [{"column": "ID", "operator": "equal"}]}, "needs a value"),
    ],
)
async def test_bad_definitions(change, message):
    async with ArchicadClient(transport=fake_transport(fake())) as c:
        with pytest.raises(ValueError, match=message):
            await model_tables.check_table_data(c, {**DEFINITION, **change}, port=19723)


async def test_definition_from_json_file(tmp_path):
    import json

    file = tmp_path / "t.json"
    file.write_text(json.dumps(DEFINITION), encoding="utf-8")
    async with ArchicadClient(transport=fake_transport(fake())) as c:
        result = await model_tables.check_table_data(c, definition_path=str(file), port=19723)
    assert result["table"] == "Luminárias"
