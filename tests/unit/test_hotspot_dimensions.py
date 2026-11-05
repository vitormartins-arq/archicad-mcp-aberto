"""Linear dimensions between hotspots, against the simulated Archicad add-on."""

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import hotspot_dimensions as tool
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio

FAVORITE = "COTA ELETRICA"
SETTINGS = {
    "layerIndex": 7,
    "linePen": 3,
    "textPosition": 1,
    "textDirection": 1,
    "appearance": 1,
    "marker": {"type": 2, "pen": 3, "size": 2.0},
    "note": {"size": 2.0, "pen": 3, "fontIndex": 5, "frame": False},
}


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


FIRST = "7D660653-AD2B-4960-B5C3-2FD6FFAFFABB"
SECOND = "7ABB5C3E-EA37-4508-A754-AC4901989200"


def model():
    fake = FakeArchicad(
        19723,
        stories=[{"index": 0, "name": "Térreo", "level": 0.0}],
        elements={FIRST: "Object", SECOND: "Object"},
    )
    row = {"type": "Object", "floorIndex": 0, "layerIndex": 1, "details": {}}
    fake.details = {FIRST: dict(row), SECOND: dict(row)}
    fake.dimension_favorites = {FAVORITE: SETTINGS}
    fake.element_hotspots = {
        FIRST: {
            "elementType": 5,
            "floorIndex": 0,
            "origin": {"x": 1.0, "y": 2.0},
            "angle": 0.0,
            "hotspots": [
                {"neigId": 13, "inIndex": 4, "x": 1.2, "y": 2.0, "z": 0.3},
                {"neigId": 13, "inIndex": 9, "x": 1.0, "y": 2.0, "z": 0.3},
            ],
        },
        SECOND: {
            "elementType": 5,
            "floorIndex": 0,
            "hotspots": [{"neigId": 13, "inIndex": 2, "x": 3.0, "y": 2.0, "z": 0.3}],
        },
    }
    return fake


def dimension(first, second, **witness):
    return {
        "reference_point": {"x": 0.0, "y": 1.0},
        "direction": {"x": 1.0, "y": 0.0},
        "witnesses": [
            {"element_guid": first, "reference": "origin", **witness},
            {"element_guid": second, "in_index": 2},
        ],
    }


async def test_origin_is_chosen_by_coordinate_and_the_favorite_reaches_the_add_on():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        first, second = FIRST, SECOND
        items = [dimension(first, second)]
        preview = await tool.create_linear_dimensions(c, items, FAVORITE, 19723)
        assert preview["items"][0]["parameters"]["witnessPoints"][0]["inIndex"] == 9
        assert "CreateLinearDimensions" not in fake.own_addon_calls
        result = await tool.create_linear_dimensions(
            c, items, FAVORITE, 19723, False, preview["confirmation_token"]
        )
    item = result["items"][0]
    assert item["status"] == "verified"
    request = next(r for r in fake.own_addon_requests if r["command"] == "CreateLinearDimensions")
    assert request["command"] == "CreateLinearDimensions"
    assert request["parameters"]["favorite"] == FAVORITE
    assert item["after"]["witnessPoints"][0]["inIndex"] == 9


async def test_text_the_favorite_did_not_apply_fails_verification():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        first, second = FIRST, SECOND
        fake.dimension_text_differences = ["text size"]
        items = [dimension(first, second)]
        preview = await tool.create_linear_dimensions(c, items, FAVORITE, 19723)
        result = await tool.create_linear_dimensions(
            c, items, FAVORITE, 19723, False, preview["confirmation_token"]
        )
    assert result["items"][0]["status"] == "verification_failed"
    assert result["items"][0]["mismatches"] == ["text size"]


async def test_a_setting_the_favorite_did_not_apply_fails_verification():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        items = [dimension(FIRST, SECOND)]
        preview = await tool.create_linear_dimensions(c, items, FAVORITE, 19723)
        fake.dimension_settings_override = {"marker": {"type": 1, "pen": 3, "size": 2.0}}
        result = await tool.create_linear_dimensions(
            c, items, FAVORITE, 19723, False, preview["confirmation_token"]
        )
    assert result["items"][0]["status"] == "verification_failed"
    assert "settings.marker.type" in result["items"][0]["mismatches"]


async def test_the_same_dimension_is_not_created_twice():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        items = [dimension(FIRST, SECOND)]
        preview = await tool.create_linear_dimensions(c, items, FAVORITE, 19723)
        await tool.create_linear_dimensions(
            c, items, FAVORITE, 19723, False, preview["confirmation_token"]
        )
        with pytest.raises(ValueError, match="already measures"):
            await tool.create_linear_dimensions(c, items, FAVORITE, 19723)


async def test_the_same_dimension_twice_in_one_plan_is_refused():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        items = [dimension(FIRST, SECOND), dimension(FIRST, SECOND)]
        with pytest.raises(ValueError, match="already measures"):
            await tool.create_linear_dimensions(c, items, FAVORITE, 19723)


async def test_a_moved_witness_element_fails_verification():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        items = [dimension(FIRST, SECOND)]
        preview = await tool.create_linear_dimensions(c, items, FAVORITE, 19723)
        fake.dimension_moves_witness = FIRST
        result = await tool.create_linear_dimensions(
            c, items, FAVORITE, 19723, False, preview["confirmation_token"]
        )
    assert result["witness_elements_unchanged"] is False
    assert result["items"][0]["mismatches"] == ["witness elements changed"]


async def test_object_without_a_hotspot_on_its_origin_is_refused():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        first, second = FIRST, SECOND
        fake.element_hotspots[first]["hotspots"].pop()
        with pytest.raises(ValueError, match="no hotspot sits"):
            await tool.create_linear_dimensions(c, [dimension(first, second)], None, 19723)


async def test_unknown_in_index_is_refused():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        first, second = FIRST, SECOND
        wrong = dimension(first, second)
        wrong["witnesses"][1]["in_index"] = 99
        with pytest.raises(ValueError, match="in_index 99"):
            await tool.create_linear_dimensions(c, [wrong], None, 19723)


async def test_reads_return_what_the_add_on_gives():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        first, second = FIRST, SECOND
        listed = await tool.list_element_hotspots(c, [first, second], 19723)
        favorite = await tool.get_dimension_favorite(c, FAVORITE, 19723)
    assert listed["elements"][0]["hotspots"][1]["inIndex"] == 9
    assert favorite["settings"]["linePen"] == 3


def test_a_witness_needs_exactly_one_reference():
    guid = "7D660653-AD2B-4960-B5C3-2FD6FFAFFABB"
    with pytest.raises(ValidationError):
        tool.Witness(element_guid=guid)
    with pytest.raises(ValidationError):
        tool.Witness(element_guid=guid, in_index=1, reference="origin")
    with pytest.raises(ValidationError):
        tool.Witness(element_guid=guid, in_index=11, line=True)


def test_a_dimension_needs_a_direction():
    guid = "7D660653-AD2B-4960-B5C3-2FD6FFAFFABB"
    with pytest.raises(ValidationError):
        tool.LinearDimension(
            reference_point={"x": 0, "y": 0},
            direction={"x": 0, "y": 0},
            witnesses=[{"element_guid": guid, "in_index": 1}] * 2,
        )


async def test_a_dimension_archicad_dropped_afterwards_fails_verification():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        items = [dimension(FIRST, SECOND)]
        preview = await tool.create_linear_dimensions(c, items, FAVORITE, 19723)
        fake.dimension_drops_witness = True
        result = await tool.create_linear_dimensions(
            c, items, FAVORITE, 19723, False, preview["confirmation_token"]
        )
    assert result["items"][0]["mismatches"] == ["witness points dropped"]


async def test_a_line_over_a_symbol_is_reported():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        fake.created_dimensions["00000000-0000-4000-8000-000000000000"] = {
            "direction": {"x": 1.0, "y": 0.0},
            "witnessPoints": [
                {"position": {"x": 0.0, "y": 2.0}},
                {"position": {"x": 5.0, "y": 2.0}},
            ],
        }
        fake.elements["00000000-0000-4000-8000-000000000000"] = "Dimension"
        crossing = await tool.check_dimensions_over_hotspots(c, [FIRST], None, 19723)
        fake.created_dimensions["00000000-0000-4000-8000-000000000000"]["witnessPoints"] = [
            {"position": {"x": 0.0, "y": 2.1}},
            {"position": {"x": 5.0, "y": 2.1}},
        ]
        near = await tool.check_dimensions_over_hotspots(c, [FIRST], None, 19723)
    assert [r["element_guid"] for r in crossing["crossing"]] == [FIRST]
    assert not near["crossing"] and [r["element_guid"] for r in near["close"]] == [FIRST]


async def test_the_plan_window_image_comes_from_the_add_on():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await tool.get_plan_window_image(
            c, {"xMin": 0, "yMin": 0, "xMax": 1, "yMax": 1}, 19723
        )
    assert result["port"] == 19723 and result["image"]
    assert fake.own_addon_requests[-1]["parameters"]["zoom"]["xMax"] == 1
