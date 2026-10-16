import json
from pathlib import Path

import httpx
import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import attribute_properties
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
CONCRETE = "AAAAAAAA-0000-4000-8000-000000000001"
BRICK = "AAAAAAAA-0000-4000-8000-000000000002"
SUPPLIER = "BBBBBBBB-0000-4000-8000-000000000001"
COST = "BBBBBBBB-0000-4000-8000-000000000002"
LOCKED = "BBBBBBBB-0000-4000-8000-000000000003"
GHOST = "BBBBBBBB-0000-4000-8000-000000000009"
tool = attribute_properties.set_attribute_property_values


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    return FakeArchicad(
        19723,
        properties={SUPPLIER: "Fornecedor", COST: "Custo", LOCKED: "Código"},
        read_only_properties={LOCKED},
        attribute_property_values={
            (CONCRETE, SUPPLIER): "",
            (CONCRETE, COST): "120,00",
            (BRICK, SUPPLIER): "Cerâmica Silva",
            (CONCRETE, LOCKED): "C-01",
        },
        **kwargs,
    )


def change(attribute=CONCRETE, prop=SUPPLIER, value="Concreteira Sul"):
    return {"attribute_guid": attribute, "property_guid": prop, "value": value}


async def apply(c, inputs):
    preview = await tool(c, inputs, 19723)
    return await tool(c, inputs, 19723, False, preview["confirmation_token"])


async def test_preview_shows_current_text_then_apply_reads_back():
    fake = model()
    inputs = [change(attribute=CONCRETE.lower()), change(prop=COST, value="135,50"), change(BRICK)]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await tool(c, inputs, 19723)
        assert "SetPropertyValuesOfAttributes" not in fake.tapir_calls
        assert [i["before"] for i in preview["items"]] == ["", "120,00", "Cerâmica Silva"]
        assert preview["items"][1]["property_name"] == "Custo"
        result = await tool(c, inputs, 19723, False, preview["confirmation_token"])
    sent = next(r for r in fake.tapir_requests if r["command"] == "SetPropertyValuesOfAttributes")
    assert sent["parameters"]["attributePropertyValues"][1] == {
        "attributeId": {"guid": CONCRETE},
        "propertyId": {"guid": COST},
        "propertyValue": {"value": "135,50"},
    }
    assert result["status"] == "verified"
    assert [i["after"] for i in result["items"]] == ["Concreteira Sul", "135,50", "Concreteira Sul"]
    assert all(i["attribute_property_receipt_id"] for i in result["items"])
    assert fake.attribute_property_values[(CONCRETE, COST)] == "135,50"


async def test_read_only_unavailable_unknown_and_repeated_refused():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="read-only"):
            await tool(c, [change(prop=LOCKED)], 19723)
        with pytest.raises(ValueError, match="not available"):
            await tool(c, [change(BRICK, COST)], 19723)
        with pytest.raises(ValueError, match="does not exist"):
            await tool(c, [change(prop=GHOST)], 19723)
        with pytest.raises(ValueError, match="only once"):
            await tool(c, [change(), change(attribute=CONCRETE.lower())], 19723)
    assert "SetPropertyValuesOfAttributes" not in fake.tapir_calls


@pytest.mark.parametrize(
    "item",
    [
        change(attribute="nope"),
        change(value=12),
        change(value="x" * 10001),
        {**change(), "extra": 1},
    ],
)
async def test_invalid_inputs_refused_before_network(item):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await tool(c, [item], 19723)
    assert fake.calls == []


async def test_refused_value_reformatted_value_and_lost_response():
    fake = model(attribute_property_refused={"abc"})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [change(prop=COST, value="abc"), change()])
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]
    assert result["items"][0]["error"]["message"] == "Failed to set property value for attribute"
    fake = model(attribute_property_stored="135,5")
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [change(prop=COST, value="135,50")])
    assert result["items"][0]["status"] == "verification_failed"
    assert result["items"][0]["after"] == "135,5"
    assert result["status"] == "needs_review"
    fake = model(lose_attribute_property_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [change()])
    assert result["items"][0]["status"] == "unknown"
    assert fake.tapir_calls.count("SetPropertyValuesOfAttributes") == 1


async def test_limits_and_explicit_port():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await tool(c, [])
        with pytest.raises(ValueError):
            await tool(c, [change(value=str(i)) for i in range(101)])
        preview = await tool(c, [change()])
        with pytest.raises(ValueError, match="explicit port"):
            await tool(c, [change()], None, False, preview["confirmation_token"])


@pytest.mark.parametrize(
    "kind,wanted,stored,verified",
    [
        ("number", "1234", "1234.000", True),
        ("integer", "12", "12.000", True),
        ("number", "1.25", "1.250", True),
        ("number", "1234", "1234.001", False),
        ("string", "1234", "1234.000", False),
        ("length", "1234", "1234.000", False),
        ("number", "1,234", "1234.000", False),
        ("number", "1234", "1,234.000", False),
        ("number", "1234", "1234 kg", False),
        ("number", "NaN", "nan", False),
        ("number", "1e9999999999999999999999", "0", False),
    ],
)
async def test_scalar_numeric_formatting_is_verified_without_rewriting(
    kind, wanted, stored, verified
):
    fake = model(attribute_property_stored=stored)
    base = fake_transport(fake)

    def handler(request):
        response = base.handle_request(request)
        if json.loads(request.content)["command"] == "API.GetDetailsOfProperties":
            body = response.json()
            for row in body["result"]["propertyDefinitions"]:
                row["propertyDefinition"]["type"] = kind
            return httpx.Response(200, json=body)
        return response

    async with ArchicadClient(transport=httpx.MockTransport(handler)) as client:
        result = await apply(client, [change(prop=COST, value=wanted)])
    item = result["items"][0]
    assert item["status"] == ("verified" if verified else "verification_failed")
    assert item["after"] == stored
    assert fake.tapir_calls.count("SetPropertyValuesOfAttributes") == 1


def test_live_number_capture_matches_value_without_changing_receipt_text():
    fixture = json.loads(
        (Path(__file__).parents[1] / "fixtures" / "ac30_3001_bra_attribute_number_live.json")
        .read_text(encoding="utf-8")
    )
    definition = fixture["number_definition"]["propertyDefinitions"][0]["propertyDefinition"]
    actual = fixture["number_readback"]["propertyValuesForAttributes"][0]["propertyValues"][0]
    item = {
        "property_type": definition["type"],
        "after": actual["propertyValue"]["value"],
        "parameters": {"propertyValue": {"value": fixture["requested_value"]}},
    }
    assert fixture["provenance"]["live_capture"] is True
    assert attribute_properties._equivalent(item)
    assert item["after"] == "1235.000"
