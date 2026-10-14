import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import property_definitions as pd
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
CUSTOM = "66666666-6666-4666-8666-000000000002"
WALL_ITEM = "A1000000-0000-4000-8000-000000000001"
MISSING = "99999999-9999-4999-8999-999999999999"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


async def apply(tool, c, inputs):
    preview = await tool(c, inputs, 19723)
    return await tool(c, inputs, 19723, False, preview["confirmation_token"])


def stored(fake, name):
    return next(p for p in fake.custom_properties if p["propertyName"] == name)


async def test_list_property_groups():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await pd.list_property_groups(c, 19723)
    assert result["groups"] == [
        {
            "group_guid": "66666666-6666-4666-8666-000000000001",
            "name": "Geral",
            "description": "",
            "is_custom": False,
            "property_count": 0,
        },
        {
            "group_guid": CUSTOM,
            "name": "Projeto",
            "description": "Dados do escritório",
            "is_custom": True,
            "property_count": 1,
        },
    ]


async def test_create_property_groups():
    fake = FakeArchicad(19723)
    groups = [{"name": "Obra", "description": "Dados da obra"}, {"name": "Custos"}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await pd.create_property_groups(c, groups, 19723)
        assert "CreatePropertyGroups" not in fake.tapir_calls
        token = preview["confirmation_token"]
        result = await pd.create_property_groups(c, groups, 19723, False, token)
        with pytest.raises(ValueError, match="consumed"):
            await pd.create_property_groups(c, groups, 19723, False, token)
    assert result["status"] == "verified"
    assert [g["name"] for g in fake.property_groups][-2:] == ["Obra", "Custos"]
    request = next(r for r in fake.tapir_requests if r["command"] == "CreatePropertyGroups")
    assert request["parameters"]["propertyGroups"][1] == {
        "propertyGroup": {"name": "Custos", "description": ""}
    }


async def test_property_group_refusals_and_outcomes():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="already exists"):
            await pd.create_property_groups(c, [{"name": "projeto"}])
        with pytest.raises(ValueError, match="twice"):
            await pd.create_property_groups(c, [{"name": "A"}, {"name": "a"}])
        for bad in ([], [{"name": " A"}], [{"name": ""}], [{"name": "A", "x": 1}]):
            with pytest.raises((ValueError, ValidationError)):
                await pd.create_property_groups(c, bad)
    assert "CreatePropertyGroups" not in fake.tapir_calls
    fake = FakeArchicad(19723, property_group_errors={0: {"error": {"code": 1, "message": "no"}}})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(pd.create_property_groups, c, [{"name": "A"}, {"name": "B"}])
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]
    fake = FakeArchicad(19723, lose_property_definition_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(pd.create_property_groups, c, [{"name": "A"}])
    assert result["items"][0]["status"] == "unknown"


async def test_create_properties_of_several_types():
    fake = FakeArchicad(19723)
    props = [
        {"name": "Lote", "group": "Projeto", "type": "string", "default": "12"},
        {
            "name": "Pé-direito",
            "group": CUSTOM.lower(),
            "type": "length",
            "default": 3,
            "editable": False,
            "available_for": ["parede"],  # BRA shows the item text in its id
        },
        {
            "name": "Acabamento",
            "group": "projeto",
            "type": "singleEnum",
            "enum_values": ["Pintura", "Cerâmica"],
            "default": "Cerâmica",
            "available_for_system": "ARCHICAD Classification",
        },
        {
            "name": "Usos",
            "group": "Projeto",
            "type": "multiEnum",
            "enum_values": ["Sala", "Quarto", "Cozinha"],
            "default": ["Quarto", "Sala"],
        },
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await pd.create_properties(c, props, 19723)
        assert "CreatePropertyDefinitions" not in fake.tapir_calls
        assert preview["items"][0]["warning"].startswith("Available for no classification")
        assert preview["items"][1]["availability_count"] == 1
        assert preview["items"][2]["availability_count"] == 5
        result = await pd.create_properties(c, props, 19723, False, preview["confirmation_token"])
    assert [i["status"] for i in result["items"]] == ["verified"] * 4
    assert result["items"][0]["default_display"] == "12"
    length = stored(fake, "Pé-direito")
    assert (length["propertyMeasureType"], length["propertyIsEditable"]) == ("Length", False)
    request = next(r for r in fake.tapir_requests if r["command"] == "CreatePropertyDefinitions")
    definitions = [d["propertyDefinition"] for d in request["parameters"]["propertyDefinitions"]]
    assert definitions[1]["defaultValue"] == {
        "basicDefaultValue": {"type": "length", "status": "normal", "value": 3.0}
    }
    assert definitions[1]["availability"] == [{"classificationItemId": {"guid": WALL_ITEM}}]
    assert definitions[2]["defaultValue"]["basicDefaultValue"]["value"] == {
        "type": "displayValue",
        "displayValue": "Cerâmica",
    }
    assert definitions[3]["defaultValue"]["basicDefaultValue"]["value"] == [
        {"enumValueId": {"type": "displayValue", "displayValue": "Quarto"}},
        {"enumValueId": {"type": "displayValue", "displayValue": "Sala"}},
    ]
    assert definitions[0]["group"] == {"propertyGroupId": {"guid": CUSTOM}}


@pytest.mark.parametrize(
    "prop",
    [
        {"type": "singleEnum"},
        {"type": "string", "enum_values": ["A"]},
        {"type": "singleEnum", "enum_values": ["A", "a"]},
        {"type": "singleEnum", "enum_values": ["A"], "default": "B"},
        {"type": "multiEnum", "enum_values": ["A"], "default": []},
        {"type": "integer", "default": 1.5},
        {"type": "boolean", "default": 1},
        {"type": "length", "default": True},
        {"type": "stringList", "default": "x"},
        {"type": "text"},
        {"type": "string", "available_for": [" "]},
    ],
)
def test_property_input_refusals(prop):
    with pytest.raises(ValidationError):
        pd.PropertyCreate.model_validate({"name": "P", "group": "Projeto", **prop})


async def test_property_plan_refusals():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        cases = [
            ({"name": "fase", "group": "Projeto", "type": "string"}, "already exists"),
            ({"name": "X", "group": "Geral", "type": "string"}, "built in"),
            ({"name": "X", "group": "Nada", "type": "string"}, "does not exist"),
            (
                {"name": "X", "group": "Projeto", "type": "string", "available_for": [MISSING]},
                "not found",
            ),
            (
                {"name": "X", "group": "Projeto", "type": "string", "available_for": ["Nada"]},
                "not found",
            ),
            (
                {"name": "X", "group": "Projeto", "type": "string", "available_for_system": "Nada"},
                "does not exist",
            ),
        ]
        for prop, message in cases:
            with pytest.raises(ValueError, match=message):
                await pd.create_properties(c, [prop])
        with pytest.raises(ValueError, match="twice"):
            await pd.create_properties(
                c,
                [
                    {"name": "X", "group": "Projeto", "type": "string"},
                    {"name": "x", "group": CUSTOM, "type": "integer"},
                ],
            )
        with pytest.raises(ValueError, match="between 1 and 50"):
            await pd.create_properties(
                c, [{"name": "X", "group": "Projeto", "type": "string"}] * 51
            )
    assert "CreatePropertyDefinitions" not in fake.tapir_calls


async def test_property_failed_mismatch_and_lost():
    prop = {"name": "X", "group": "Projeto", "type": "string", "available_for": [WALL_ITEM.lower()]}
    error = {"error": {"code": -1, "message": "failed to create the property"}}
    fake = FakeArchicad(19723, property_create_errors={0: error})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(pd.create_properties, c, [prop, {**prop, "name": "Y"}])
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]
    fake = FakeArchicad(19723, property_drops_availability=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(pd.create_properties, c, [prop])
    assert result["items"][0]["status"] == "verification_failed"
    assert result["items"][0]["mismatches"] == ["availability"]
    fake = FakeArchicad(19723, lose_property_definition_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(pd.create_properties, c, [prop])
        preview = await pd.create_properties(c, [{**prop, "name": "Z"}])
        with pytest.raises(ValueError, match="explicit port"):
            await pd.create_properties(
                c, [{**prop, "name": "Z"}], None, False, preview["confirmation_token"]
            )
    assert result["items"][0]["status"] == "unknown"
    assert fake.tapir_calls.count("CreatePropertyDefinitions") == 1


async def test_property_plan_changed_since_preview():
    fake = FakeArchicad(19723)
    prop = {"name": "X", "group": "Projeto", "type": "string"}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await pd.create_properties(c, [prop], 19723)
        fake.custom_properties.append({**fake.custom_properties[0], "propertyName": "X"})
        with pytest.raises(ValueError, match="already exists"):
            await pd.create_properties(c, [prop], 19723, False, preview["confirmation_token"])
    assert "CreatePropertyDefinitions" not in fake.tapir_calls
