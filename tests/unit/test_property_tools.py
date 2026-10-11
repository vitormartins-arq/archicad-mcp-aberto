"""SetPropertyValuesOfElements safety tests. Every request goes through MockTransport."""

import json
from pathlib import Path

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.connection.errors import AmbiguousTarget
from archicad_mcp_aberto.tools import write
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
A = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
B = "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"
MISSING = "CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC"
TEXT = "11111111-1111-1111-1111-111111111111"
LENGTH = "22222222-2222-2222-2222-222222222222"
ENUM = "33333333-3333-3333-3333-333333333333"


@pytest.fixture(autouse=True)
def receipt_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path / "receipts"))
    return tmp_path / "receipts"


def value(kind, v, status="normal"):
    return {"type": kind, "status": status, "value": v}


def model(**changes):
    values = {
        (A, TEXT): value("string", "antigo"),
        (A, LENGTH): value("length", 2.5),
        (B, TEXT): value("string", "outro"),
        (A, ENUM): {"type": "singleEnum", "status": "normal", "value": {"displayValue": "x"}},
    }
    values.update(changes.pop("property_values", {}))
    return FakeArchicad(
        19723,
        elements={A: "Wall", B: "Slab"},
        properties={TEXT: "Acabamento", LENGTH: "Largura", ENUM: "Fase"},
        property_values=values,
        **changes,
    )


def change(element=A, prop=TEXT, new="novo"):
    return {"element_guid": element, "property_guid": prop, "value": new}


def client(*instances):
    return ArchicadClient(transport=fake_transport(*instances))


async def apply(c, changes, port=19723):
    preview = await write.set_property_values(c, changes, port)
    return await write.set_property_values(c, changes, port, False, preview["confirmation_token"])


async def test_preview_shows_current_and_new_value(receipt_directory):
    fake = model()
    async with client(fake) as c:
        result = await write.set_property_values(c, [change(A.lower(), TEXT.lower())])
    item = result["items"][0]
    assert result["dry_run"] is True
    assert item["property_name"] == "Acabamento"
    assert item["before"] == value("string", "antigo")
    assert item["parameters"]["propertyValue"] == value("string", "novo")
    assert fake.property_values[(A, TEXT)]["value"] == "antigo"
    assert "API.SetPropertyValuesOfElements" not in fake.calls
    assert not receipt_directory.exists()


async def test_apply_writes_and_reads_back():
    fake = model()
    async with client(fake) as c:
        result = await apply(c, [change(), change(prop=LENGTH, new=3), change(B, TEXT, "b")])
    assert result["status"] == "verified"
    assert fake.property_values[(A, LENGTH)] == value("length", 3.0)
    assert fake.property_values[(B, TEXT)]["value"] == "b"
    assert fake.calls.count("API.SetPropertyValuesOfElements") == 1
    saved = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
    assert all(i["change_receipt_id"] for i in saved["items"])


@pytest.mark.parametrize(
    ("prop", "new", "message"),
    [
        (TEXT, 3, "needs text"),
        (LENGTH, "3 m", "needs a number"),
        (LENGTH, True, "needs a number"),
        (ENUM, "x", "not supported"),
    ],
)
async def test_wrong_value_type_is_refused_in_preview(prop, new, message):
    fake = model()
    async with client(fake) as c:
        with pytest.raises(ValueError, match=message):
            await write.set_property_values(c, [change(prop=prop, new=new)])
    assert "API.SetPropertyValuesOfElements" not in fake.calls


async def test_integer_and_boolean_values():
    fake = model(
        property_values={
            (A, TEXT): value("integer", 1),
            (A, LENGTH): value("boolean", False),
        }
    )
    async with client(fake) as c:
        with pytest.raises(ValueError, match="whole number"):
            await write.set_property_values(c, [change(new=1.5)])
        result = await apply(c, [change(new=2.0), change(prop=LENGTH, new=True)])
    assert result["status"] == "verified"
    assert fake.property_values[(A, TEXT)] == value("integer", 2)
    assert fake.property_values[(A, LENGTH)] == value("boolean", True)


async def test_read_only_and_unavailable_properties_are_refused():
    fake = model(read_only_properties={TEXT})
    async with client(fake) as c:
        with pytest.raises(ValueError, match="read-only"):
            await write.set_property_values(c, [change()])
    fake = model(property_values={(A, LENGTH): value("length", 0, "notAvailable")})
    async with client(fake) as c:
        with pytest.raises(ValueError, match="not available"):
            await write.set_property_values(c, [change(prop=LENGTH, new=1)])


async def test_unknown_element_is_refused_in_preview():
    fake = model()
    async with client(fake) as c:
        with pytest.raises(ValueError, match="cannot read"):
            await write.set_property_values(c, [change(MISSING)])


async def test_duplicates_bounds_and_bad_guids_before_any_request():
    fake = model()
    async with client(fake) as c:
        with pytest.raises(ValueError, match="only once"):
            await write.set_property_values(c, [change(), change(A.lower(), TEXT, "y")])
        with pytest.raises(ValueError, match="between 1 and 100"):
            await write.set_property_values(c, [])
        with pytest.raises(ValueError):
            await write.set_property_values(c, [change("nope")])
    assert fake.calls == []


async def test_value_changed_since_preview_is_refused():
    fake = model()
    async with client(fake) as c:
        preview = await write.set_property_values(c, [change()], 19723)
        fake.property_values[(A, TEXT)] = value("string", "mudou")
        with pytest.raises(ValueError, match="changed since preview"):
            await write.set_property_values(
                c, [change()], 19723, False, preview["confirmation_token"]
            )
    assert "API.SetPropertyValuesOfElements" not in fake.calls


async def test_token_single_use_and_explicit_port():
    fake = model()
    async with client(fake) as c:
        preview = await write.set_property_values(c, [change()], 19723)
        with pytest.raises(ValueError, match="explicit port"):
            await write.set_property_values(
                c, [change()], None, False, preview["confirmation_token"]
            )
        await write.set_property_values(c, [change()], 19723, False, preview["confirmation_token"])
        with pytest.raises(ValueError, match="already consumed"):
            await write.set_property_values(
                c, [change()], 19723, False, preview["confirmation_token"]
            )
    assert fake.calls.count("API.SetPropertyValuesOfElements") == 1


async def test_native_failure_is_kept_per_change():
    error = {"success": False, "error": {"code": 4010, "message": "Property is not editable"}}
    fake = model(property_set_errors={0: error})
    async with client(fake) as c:
        result = await apply(c, [change(), change(B, TEXT, "b")])
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]
    assert result["items"][0]["error"] == error["error"]


async def test_success_without_change_fails_verification():
    fake = model(property_set_ignored=True)
    async with client(fake) as c:
        result = await apply(c, [change()])
    assert result["items"][0]["status"] == "verification_failed"
    assert result["status"] == "needs_review"


async def test_two_instances_require_explicit_target():
    first, second = model(), FakeArchicad(19724, elements={A: "Wall"})
    async with client(first, second) as c:
        with pytest.raises(AmbiguousTarget):
            await write.set_property_values(c, [change()])
