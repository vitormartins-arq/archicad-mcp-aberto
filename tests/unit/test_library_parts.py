import json
from copy import deepcopy
from pathlib import Path

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import read, write
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "tapir170_library_parts_documented.json").read_text(
        encoding="utf-8"
    )
)
PART = FIXTURE["response"]["libraryParts"][0]


def obj(name="Mesa Retangular 30"):
    return {
        "library_part_name": name,
        "origin": {"x": 0, "y": 0},
        "floor_index": 0,
        "base_level": 0,
    }


async def test_catalog_has_guid_name_index_type_and_source():
    fake = FakeArchicad(19723, library_inventory=[deepcopy(PART)])
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await read.list_library_parts(c, 19723)
    assert result["total"] == 1
    assert result["libraryParts"][0] == {**PART, "name": PART["documentName"]}
    assert result["partial"] is False
    assert fake.tapir_calls == ["GetAvailableLibraryParts"]
    assert FIXTURE["provenance"]["live_capture"] is False


async def test_case_insensitive_filter_and_pagination():
    fake = FakeArchicad(19723, library_parts={"Table Alpha", "Table Beta", "Chair"})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await read.list_library_parts(c, 19723, "TABLE", 1, 1)
    assert result["total"] == 2 and len(result["libraryParts"]) == 1
    assert result["libraryParts"][0]["name"] == "Table Beta"


async def test_empty_catalog_and_empty_page():
    fake = FakeArchicad(19723, library_inventory=[])
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await read.list_library_parts(c, 19723, offset=50)
    assert result["total"] == 0 and result["libraryParts"] == []


async def test_includes_other_part_types_and_filename_fallback():
    row = {**PART, "typeId": "Macro", "documentName": "", "fileName": "macro.gsm"}
    async with ArchicadClient(
        transport=fake_transport(FakeArchicad(19723, library_inventory=[row]))
    ) as c:
        result = await read.list_library_parts(c, 19723)
    assert result["libraryParts"][0]["name"] == "macro.gsm"
    assert result["libraryParts"][0]["typeId"] == "Macro"


async def test_partial_inventory_exposed_and_unknown_name_not_declared_absent():
    fake = FakeArchicad(19723, library_skipped_count=2)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await read.list_library_parts(c, 19723)
        assert result["partial"] is True and result["skippedCount"] == 2
        with pytest.raises(ValueError, match="partial; cannot confirm"):
            await write.create_objects(c, [obj("Unknown")], 19723)
    assert "CreateObjects" not in fake.tapir_calls


@pytest.mark.parametrize(
    "kwargs", [{"limit": 501}, {"limit": 0}, {"offset": -1}, {"name_contains": 1}]
)
async def test_invalid_read_input_before_requests(kwargs):
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await read.list_library_parts(c, **kwargs)
    assert not fake.calls


async def test_one_catalog_call_for_object_batch():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await write.create_objects(c, [obj(), obj()], 19723)
    assert fake.tapir_calls.count("GetAvailableLibraryParts") == 1
    assert preview["items"][0]["library_part_guid"]
    assert "CreateObjects" not in fake.tapir_calls


async def test_non_object_name_not_accepted():
    fake = FakeArchicad(19723, library_inventory=[{**PART, "typeId": "Lamp"}])
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="name not in loaded Object"):
            await write.create_objects(c, [obj()], 19723)
    assert "CreateObjects" not in fake.tapir_calls


async def test_ambiguous_names_refused():
    fake = FakeArchicad(
        19723,
        library_inventory=[
            deepcopy(PART),
            {**PART, "guid": "44444444-4444-4444-4444-444444444444"},
        ],
    )
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="Ambiguous library part"):
            await write.create_objects(c, [obj()], 19723)


async def test_catalog_identity_change_requires_new_preview():
    fake = FakeArchicad(19723, library_inventory=[deepcopy(PART)])
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await write.create_objects(c, [obj()], 19723)
        fake.library_inventory[0]["guid"] = "44444444-4444-4444-4444-444444444444"
        with pytest.raises(ValueError, match="changed"):
            await write.create_objects(c, [obj()], 19723, False, preview["confirmation_token"])
    assert "CreateObjects" not in fake.tapir_calls


async def test_part_removed_after_preview_refused():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await write.create_objects(c, [obj()], 19723)
        fake.library_parts.clear()
        with pytest.raises(ValueError, match="name not in loaded"):
            await write.create_objects(c, [obj()], 19723, False, preview["confirmation_token"])
    assert "CreateObjects" not in fake.tapir_calls


@pytest.mark.parametrize(
    "replacement",
    [{}, {"libraryParts": [], "skippedCount": True}, {"libraryParts": [{}], "skippedCount": 0}],
)
async def test_malformed_catalog_refused(monkeypatch, replacement):
    original = FakeArchicad._tapir

    def malformed(self, params):
        if params["addOnCommandId"]["commandName"] == "GetAvailableLibraryParts":
            return {"succeeded": True, "result": {"addOnCommandResponse": replacement}}
        return original(self, params)

    monkeypatch.setattr(FakeArchicad, "_tapir", malformed)
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="Unexpected library"):
            await write.create_objects(c, [obj()], 19723)
    assert "CreateObjects" not in fake.tapir_calls
