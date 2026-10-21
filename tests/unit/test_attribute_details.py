"""Attribute detail reads use source-derived fixtures and simulated Archicad only."""

import json
from pathlib import Path

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import attributes_details
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
GUID = "A1000000-0000-4000-8000-000000000001"


@pytest.mark.parametrize("kind", list(attributes_details.KINDS))
async def test_each_closed_kind_preserves_details(kind):
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        result = await attributes_details.get_attribute_details(client, kind, [GUID], 19723)
    assert result["kind"] == kind and result["items"][0]["guid"] == GUID
    assert "details" in result["items"][0]


async def test_inventory_and_per_item_error():
    fake = FakeArchicad(19723)
    missing = "A1000000-0000-4000-8000-000000000099"
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        all_rows = await attributes_details.get_attribute_details(client, "composites", port=19723)
        mixed = await attributes_details.get_attribute_details(
            client, "composites", [GUID, missing], 19723
        )
    assert all_rows["total"] == 1
    assert "details" in mixed["items"][0] and "error" in mixed["items"][1]


async def test_invalid_inputs():
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as client:
        with pytest.raises(ValueError):
            await attributes_details.get_attribute_details(client, "walls", [], 19723)
        with pytest.raises(ValueError):
            await attributes_details.get_attribute_details(client, "fills", ["bad"], 19723)
        with pytest.raises(ValueError, match="500"):
            await attributes_details.get_attribute_details(client, "fills", [GUID] * 501, 19723)


def test_fixture_provenance():
    fixture = json.loads(
        (
            Path(__file__).parents[1] / "fixtures" / "tapir170_attribute_details_documented.json"
        ).read_text()
    )
    assert fixture["provenance"]["live_capture"] is False
    assert fixture["provenance"]["kind"] == "source-derived, not a live capture"
