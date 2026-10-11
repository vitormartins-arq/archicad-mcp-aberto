from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools.read import get_element_details
from tests.unit.fake_archicad import FakeArchicad, fake_transport

GUID = "11111111-1111-1111-1111-111111111111"


@pytest.mark.anyio
@pytest.mark.parametrize("delta,removed", [(0, 1), (5e-10, 1), (2e-9, 0)])
async def test_duplicates_with_same_order(delta, removed):
    a = {"coordinates": [{"x": 0, "y": 0}, {"x": 1, "y": 1}]}
    b = deepcopy(a)
    b["coordinates"][0]["x"] += delta
    reverse = {"coordinates": list(reversed(a["coordinates"]))}
    fake = FakeArchicad(19723, elements={GUID: "Wall"}, cut_fills={GUID: [a, b, reverse]})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await get_element_details(c, [GUID], 19723, ["floorPlanPolygons"])
    assert len(result["detailsOfElements"][0]["floorPlanPolygons"]) == 3 - removed
    assert bool(result.get("notes")) == bool(removed)
    if removed:
        assert "Removed 1" in result["notes"][0]


@pytest.mark.anyio
async def test_missing_polygon_keeps_existing_note():
    fake = FakeArchicad(19723, elements={GUID: "Wall"})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await get_element_details(c, [GUID], 19723, ["floorPlanPolygons"])
    assert result["detailsOfElements"][0]["floorPlanPolygons"] == []
    assert "cut fill" in result["note"]
