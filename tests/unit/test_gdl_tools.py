import json
from copy import deepcopy
from pathlib import Path

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import edit, read
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
GUID = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
PARAMS = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "tapir170_gdl_parameters_documented.json").read_text(
        encoding="utf-8"
    )
)["parameters"]


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    return FakeArchicad(
        19723,
        elements={GUID: "Object"},
        details={GUID: {"type": "Object", "floorIndex": 0, "layerIndex": 1}},
        gdl_parameters={GUID: deepcopy(PARAMS)},
        **kwargs,
    )


def change(name="A", value=2.0):
    return {"element_guid": GUID, "name": name, "value": value}


async def apply(c, changes):
    preview = await edit.set_gdl_parameters(c, changes, 19723)
    return await edit.set_gdl_parameters(c, changes, 19723, False, preview["confirmation_token"])


async def test_read_preserves_metadata_and_per_element_errors():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await read.get_gdl_parameters(c, [GUID, OTHER], 19723)
    rows = result["gdlParametersOfElements"]
    assert rows[0]["parameters"] == PARAMS
    assert "error" in rows[1]
    assert "SetGDLParametersOfElements" not in fake.tapir_calls


async def test_preview_and_scalar_write_verify_each_change():
    fake = model()
    changes = [change(), change("label", "New desk"), change("enabled", False)]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await edit.set_gdl_parameters(c, changes, 19723)
        assert preview["items"][0]["before"]["value"] == 1.0
        assert preview["items"][0]["parameters"]["gdlParameters"][0]["value"] == 2.0
        assert "SetGDLParametersOfElements" not in fake.tapir_calls
        result = await edit.set_gdl_parameters(
            c, changes, 19723, False, preview["confirmation_token"]
        )
        with pytest.raises(ValueError, match="consumed"):
            await edit.set_gdl_parameters(c, changes, 19723, False, preview["confirmation_token"])
    assert result["counts"]["verified"] == 3
    assert len({i["gdl_receipt_id"] for i in result["items"]}) == 3
    assert result["receipt_path"]


@pytest.mark.parametrize("flag", ["Fixed", "Hidden", "HiddenFromScript", "Disabled"])
async def test_flags_refused(flag):
    fake = model()
    fake.gdl_parameters[GUID][0]["flags"] = [flag]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="refused"):
            await edit.set_gdl_parameters(c, [change()], 19723)
    assert "SetGDLParametersOfElements" not in fake.tapir_calls


@pytest.mark.parametrize(
    "metadata", [{"isLocked": True}, {"dimension1": 2}, {"value": [1, 2]}, {"type": "Dictionary"}]
)
async def test_locked_arrays_and_dictionary_refused(metadata):
    fake = model()
    fake.gdl_parameters[GUID][0].update(metadata)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await edit.set_gdl_parameters(c, [change()], 19723)
    assert "SetGDLParametersOfElements" not in fake.tapir_calls


@pytest.mark.parametrize(
    "item", [change("absent"), change("A", "2"), change("enabled", 1), change("label", 3)]
)
async def test_missing_name_and_wrong_type_refused(item):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await edit.set_gdl_parameters(c, [item], 19723)
    assert "SetGDLParametersOfElements" not in fake.tapir_calls


@pytest.mark.parametrize("reason", ["not-object", "locked", "hotlink"])
async def test_unsafe_objects_refused(reason):
    fake = model()
    if reason == "not-object":
        fake.elements[GUID] = "Wall"
        fake.details[GUID]["type"] = "Wall"
    elif reason == "locked":
        fake.locked_elements.add(GUID)
    else:
        fake.details[GUID]["hotlinkId"] = {"guid": OTHER}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await edit.set_gdl_parameters(c, [change()], 19723)


async def test_partial_native_errors():
    fake = model(gdl_errors={1: {"success": False, "error": {"code": -1, "message": "Refused"}}})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [change(), change("label", "New")])
    assert [i["status"] for i in result["items"]] == ["verified", "failed"]


async def test_ignored_parameter_is_verification_failed():
    async with ArchicadClient(transport=fake_transport(model(gdl_ignored=True))) as c:
        result = await apply(c, [change()])
    assert result["items"][0]["status"] == "verification_failed"


async def test_lost_response_consumed_and_unknown():
    fake = model(lose_gdl_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await edit.set_gdl_parameters(c, [change()], 19723)
        result = await edit.set_gdl_parameters(
            c, [change()], 19723, False, preview["confirmation_token"]
        )
        with pytest.raises(ValueError, match="consumed"):
            await edit.set_gdl_parameters(
                c, [change()], 19723, False, preview["confirmation_token"]
            )
    assert result["items"][0]["status"] == "unknown"


@pytest.mark.parametrize(
    "changes", [[], [change()] * 101, [change(), change()], [change(value=float("nan"))]]
)
async def test_input_limits_before_network(changes):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await edit.set_gdl_parameters(c, changes)
    assert not fake.calls


async def test_changed_current_value_invalidates_preview():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await edit.set_gdl_parameters(c, [change()], 19723)
        fake.gdl_parameters[GUID][0]["value"] = 5
        with pytest.raises(ValueError, match="changed"):
            await edit.set_gdl_parameters(
                c, [change()], 19723, False, preview["confirmation_token"]
            )
    assert "SetGDLParametersOfElements" not in fake.tapir_calls
