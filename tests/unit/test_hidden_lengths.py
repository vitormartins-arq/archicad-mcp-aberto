"""Synthetic editable-hotspot length metadata; no private library source."""

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import edit, gdl
from tests.unit.fake_archicad import fake_transport
from tests.unit.test_lamp_gdl import GUID, apply, model


def row(**overrides):
    return (
        dict(
            name="symbol_offset",
            type="Length",
            value=0.0,
            flags=["Hidden", "HiddenFromScript"],
            isLocked=False,
        )
        | overrides
    )


@pytest.mark.parametrize("flags", [["Fixed"], ["Disabled"], ["Hidden", "Fixed"]])
def test_hard_flags_remain_blocked(flags):
    with pytest.raises(ValueError):
        edit._gdl_value(row(flags=flags), 0.4, allow_hidden_length=True, allow_script_hidden=True)
    assert gdl.blocked_reason(row(flags=flags), allow_hidden_length=True, allow_script_hidden=True)


@pytest.mark.parametrize("overrides", [{"isLocked": True}, {"type": "String"}, {"dimension1": 2}])
def test_hidden_consent_is_scalar_length_only(overrides):
    assert gdl.blocked_reason(row(**overrides), allow_hidden_length=True, allow_script_hidden=True)


def test_defaults_and_separate_script_consent_still_block():
    for kwargs in ({}, {"allow_hidden_length": True}, {"allow_script_hidden": True}):
        with pytest.raises(ValueError):
            edit._gdl_value(row(), 0.4, **kwargs)
    with pytest.raises(ValueError, match="reason"):
        edit.GDLChange(element_guid=GUID, name="symbol_offset", value=0.4, allow_hidden_length=True)


@pytest.mark.anyio
async def test_hidden_length_preview_receipt_and_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))
    fake = model()
    fake.gdl_parameters[GUID] = [row()]
    changes = [
        dict(
            element_guid=GUID,
            name="symbol_offset",
            value=0.4,
            allow_hidden_length=True,
            allow_script_hidden=True,
            hidden_edit_reason="Reviewed editable hotspot in authoring source.",
        )
    ]
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        result = await apply(client, changes)
    assert result["items"][0]["status"] == "verified"
    assert result["items"][0]["after"]["value"] == 0.4
    assert result["items"][0]["hidden_edit_reason"] == changes[0]["hidden_edit_reason"]
