"""Tapir 1.7.0 Design Options reads; simulated only, never live Archicad."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import design_options
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio

WALL = "11111111-1111-1111-1111-111111111111"
SLAB = "22222222-2222-2222-2222-222222222222"
OPTION = "20000000-0000-4000-8000-000000000001"
MISSING = "99999999-9999-4999-8999-999999999999"
FIXTURE = json.loads(
    (Path(__file__).parents[1] / "fixtures" / "tapir170_design_options_documented.json").read_text()
)


def client(fake):
    return ArchicadClient(transport=fake_transport(fake))


async def test_inventory_normalizes_relationships_filters_and_pages():
    fake = FakeArchicad(19723, elements={WALL: "Wall", SLAB: "Slab"})
    async with client(fake) as c:
        result = await design_options.list_design_options(c, 19723, query="brick", limit=1)
    assert result["total_options"] == 1
    assert result["options"][0] == {
        "guid": OPTION,
        "id": "F-01",
        "name": "Brick",
        "owner_set_name": "Facade",
    }
    assert result["sets"][0]["design_option_guids"] == [
        OPTION,
        "20000000-0000-4000-8000-000000000002",
    ]
    assert result["combinations"][0]["active_design_option_guids"] == [OPTION]
    assert [r["command"] for r in fake.tapir_requests] == [
        "GetDesignOptionSets",
        "GetDesignOptions",
        "GetDesignOptionCombinations",
    ]


async def test_elements_of_options_preserves_native_errors_and_request_shape():
    fake = FakeArchicad(19723, elements={WALL: "Wall"})
    async with client(fake) as c:
        result = await design_options.get_elements_of_design_options(c, [OPTION, MISSING], 19723)
    assert result["items"][0]["element_guids"] == [WALL]
    assert result["items"][1]["design_option_guid"] == MISSING
    assert result["items"][1]["error"]["code"] == -2
    assert fake.tapir_requests[-1]["parameters"] == {
        "designOptions": [
            {"designOptionId": {"guid": OPTION}},
            {"designOptionId": {"guid": MISSING}},
        ]
    }


async def test_element_membership_distinguishes_linked_main_and_missing():
    fake = FakeArchicad(19723, elements={WALL: "Wall", SLAB: "Slab"})
    async with client(fake) as c:
        result = await design_options.get_design_options_for_elements(
            c, [WALL, SLAB, MISSING], 19723
        )
    assert [row["status"] for row in result["items"]] == [
        "LinkedToDesignOption",
        "NotLinkedToAnyDesignOption",
        "NotExistingElement",
    ]
    assert result["items"][0]["design_option"]["guid"] == OPTION


@pytest.mark.parametrize("values", [[], [OPTION, OPTION], ["bad-guid"]])
async def test_guid_inputs_are_bounded_valid_and_unique(values):
    async with client(FakeArchicad(19723)) as c:
        with pytest.raises(ValueError):
            await design_options.get_elements_of_design_options(c, values, 19723)


async def test_malformed_inventory_is_rejected_instead_of_partially_returned(monkeypatch):
    fake = FakeArchicad(19723)
    original = deepcopy(FIXTURE["options"])
    original[0]["designOptionId"] = {"guid": "bad"}
    monkeypatch.setitem(
        FIXTURE, "options", original
    )  # local fixture proves source data stays synthetic
    # Corrupt the fake's global source response for this call only.
    from tests.unit import fake_archicad

    monkeypatch.setitem(fake_archicad.DESIGN_OPTIONS_FIXTURE, "options", original)
    async with client(fake) as c:
        with pytest.raises(ValueError, match="design option GUID"):
            await design_options.list_design_options(c, 19723)


def test_fixture_provenance_is_source_derived_and_not_live():
    assert FIXTURE["provenance"]["live_capture"] is False
    assert FIXTURE["provenance"]["tapir_version"] == "1.7.0"
    assert FIXTURE["provenance"]["commit"] == "02691b5d680b60c73317e8e49b78ab14dfd4c9d8"
