"""Synthetic Lamp fixtures matching AC30/Tapir 1.7.3 metadata shapes, not private GDL."""

from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import edit, gdl, parameters, read
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
GUID = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
ROWS = [
    dict(
        name="fx_code",
        type="String",
        value="F1",
        flags=["HiddenFromScript", "Child"],
        isLocked=False,
    ),
    dict(
        name="fx_power",
        type="RealNumber",
        value=9.0,
        flags=["HiddenFromScript"],
        isLocked=False,
        possibleValues=[dict(value=0, flag="GreaterThanOrEqual")],
        canHaveCustomValue=False,
    ),
    dict(
        name="fx_kelvin",
        type="Integer",
        value=3000,
        flags=["HiddenFromScript"],
        isLocked=False,
        possibleValues=[dict(value=0, description="RGB"), dict(value=3000), dict(value=4000)],
        canHaveCustomValue=False,
    ),
    dict(name="fx_derived", type="RealNumber", value=720.0, flags=["Hidden"], isLocked=True),
]


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(kind="Lamp", **kwargs):
    return FakeArchicad(
        19723,
        elements={GUID: kind},
        details={
            GUID: dict(
                type=kind,
                floorIndex=0,
                layerIndex=1,
                details=dict(
                    origin=dict(x=1, y=2, z=3), angle=0, dimensions=dict(x=0.5, y=0.5, z=0.4)
                ),
            )
        },
        gdl_parameters={GUID: deepcopy(ROWS)},
        **kwargs,
    )


def change(name="fx_code", value="F2", allow=True):
    return dict(element_guid=GUID, name=name, value=value, allow_script_hidden=allow)


async def apply(client, changes):
    preview = await edit.set_gdl_parameters(client, changes, 19723)
    return await edit.set_gdl_parameters(
        client, changes, 19723, False, preview["confirmation_token"]
    )


@pytest.mark.parametrize("kind", ["Lamp", "Object"])
async def test_read_and_scalar_edit_with_explicit_flag_consent(kind):
    fake = model(kind)
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        before = await read.get_gdl_parameters(client, [GUID, OTHER], 19723)
        assert before["gdlParametersOfElements"][0]["type"] == kind
        assert before["gdlParametersOfElements"][0]["parameters"] == ROWS
        assert "error" in before["gdlParametersOfElements"][1]
        result = await apply(client, [change(), change("fx_power", 4.8), change("fx_kelvin", 0)])
    assert result["counts"]["verified"] == 3
    assert all(not i["dependent_changes"] for i in result["items"])
    assert result["items"][0]["identity_before"] == result["items"][0]["identity_after"]
    assert result["receipt_path"]


async def test_script_hidden_authorization_is_per_change_and_bound_to_token():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        with pytest.raises(ValueError, match="explicitly"):
            await edit.set_gdl_parameters(client, [change(allow=False)], 19723)
        preview = await edit.set_gdl_parameters(client, [change()], 19723)
        fake.details[GUID]["details"]["origin"]["x"] = 10
        with pytest.raises(ValueError, match="changed"):
            await edit.set_gdl_parameters(
                client, [change()], 19723, False, preview["confirmation_token"]
            )
    assert "SetGDLParametersOfElements" not in fake.tapir_calls


@pytest.mark.parametrize(
    "metadata",
    [
        dict(flags=["HiddenFromScript", "Hidden"]),
        dict(flags=["Disabled"]),
        dict(flags=["Fixed"]),
        dict(isLocked=True),
        dict(flags=[1]),
    ],
)
async def test_opt_in_cannot_override_other_protections(metadata):
    fake = model()
    fake.gdl_parameters[GUID][0].update(metadata)
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        with pytest.raises(ValueError):
            await edit.set_gdl_parameters(client, [change()], 19723)
    assert "SetGDLParametersOfElements" not in fake.tapir_calls


@pytest.mark.parametrize(
    "name,value",
    [
        ("fx_kelvin", 3500),
        ("fx_kelvin", "RGB"),
        ("fx_kelvin", True),
        ("fx_kelvin", 3000.5),
        ("fx_power", -1),
        ("fx_code", 2),
    ],
)
async def test_native_enum_ranges_and_types_refused_before_dispatch(name, value):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        with pytest.raises(ValueError):
            await edit.set_gdl_parameters(client, [change(name, value)], 19723)
    assert "SetGDLParametersOfElements" not in fake.tapir_calls


@pytest.mark.parametrize("value", [-1, 11, 4])
async def test_all_reported_bounds_and_steps_must_hold(value):
    row = dict(
        type="RealNumber",
        value=2,
        flags=[],
        canHaveCustomValue=False,
        possibleValues=[
            dict(value=0, flag="GreaterThanOrEqual"),
            dict(value=10, flag="LessThanOrEqual"),
            dict(flag="Step", stepBegin=0, stepValue=3),
        ],
    )
    with pytest.raises(ValueError, match="outside"):
        gdl.coerce(row, value, (1, 7, 3))
    assert gdl.coerce(row, 6, (1, 7, 3)) == (6.0, 6.0)


async def test_general_parameter_tool_uses_same_explicit_flag_policy():
    async with ArchicadClient(transport=fake_transport(model())) as client:
        preview = await parameters.set_element_parameters(client, [change()], 19723)
    assert preview["items"][0]["changes"][0]["allow_script_hidden"] is True


async def test_partial_native_failure_is_not_reported_as_success():
    fake = model(gdl_errors={1: dict(success=False, error=dict(code=-1, message="Refused"))})
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        result = await apply(client, [change(), change("fx_power", 4.8)])
    assert [i["status"] for i in result["items"]] == ["verified", "failed"]


async def test_script_side_effects_are_read_back_and_dimension_change_fails():
    fake = model()

    def script(guid, rows):
        rows[3]["value"] = 100
        fake.details[guid]["details"]["dimensions"]["x"] = 5

    fake.gdl_script = script
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        result = await apply(client, [change()])
    item = result["items"][0]
    assert item["status"] == "verification_failed"
    assert "identity.details.dimensions" in item["mismatches"]
    assert item["dependent_changes"] == [dict(name="fx_derived", before=720.0, after=100)]
