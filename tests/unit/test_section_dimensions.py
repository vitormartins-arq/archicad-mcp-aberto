"""Section cut reading and vertical dimensions inside a section, against the fake add-on."""

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import section_dimensions as tool
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio

NAV = "5A1E2F3C-0000-4000-8000-0000000000AA"
SLAB = "11111111-1111-4111-8111-111111111111"
FINISH = "22222222-2222-4222-8222-222222222222"
WALL = "33333333-3333-4333-8333-333333333333"
CEILING = "44444444-4444-4444-8444-444444444444"
FAVORITE = "COTA CORTE"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def section_element(n: int, parent: str, kind: str, y_min: float, y_max: float, x=(0.0, 4.0)):
    hotspots = []
    for i, (hx, hy) in enumerate(
        [(x[0], y_min), (x[1], y_min), (x[0], y_max), (x[1], y_max)], start=1
    ):
        hotspots.append(
            {
                "neigId": 60,
                "inIndex": i,
                "nodeType": 0,
                "subType": 0,
                "supplUnId": 1000 * n + i,
                "flags": 0,
                "x": hx,
                "y": hy,
                "z": 0.0,
            }
        )
    return {
        "sectionElementId": {"guid": f"AAAAAAAA-0000-4000-8000-{n:012d}"},
        "parentId": {"guid": parent},
        "parentType": kind,
        "parentTypeId": 0,
        "hotspots": hotspots,
    }


def model(**fake_options):
    fake = FakeArchicad(
        19723,
        stories=[{"index": 0, "name": "Térreo", "level": 0.0}],
        elements={SLAB: "Slab", FINISH: "Slab", WALL: "Wall", CEILING: "Slab"},
        **fake_options,
    )
    fake.dimension_favorites = {FAVORITE: {"linePen": 3, "note": {"size": 2.0}}}
    fake.section_cuts = {
        NAV: [
            section_element(1, SLAB, "Slab", -0.12, 0.0),
            section_element(2, FINISH, "Slab", 0.0, 0.03),
            section_element(3, WALL, "Wall", 0.03, 2.80, x=(3.9, 4.05)),
            section_element(4, CEILING, "Slab", 2.60, 2.62),
        ]
    }
    return fake


def floor_to_ceiling(station=1.0):
    return {
        "station_x": station,
        "points": [
            {"element_guid": SLAB, "at": "top"},
            {"element_guid": FINISH, "at": "top"},
            {"element_guid": CEILING, "at": "bottom"},
            {"element_guid": WALL, "at": "top"},
        ],
    }


async def test_reads_cut_elements_by_parent_with_view_extent():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await tool.get_section_cut_elements(c, NAV.lower(), 19723)
    assert result["section_element_count"] == 4
    by_guid = {e["parent_guid"]: e for e in result["elements"]}
    assert by_guid[WALL]["view_y_min"] == 0.03 and by_guid[WALL]["view_y_max"] == 2.80
    assert by_guid[CEILING]["section_elements"][0]["hotspots"][0]["suppl_un_id"] == 4001
    assert fake.own_addon_requests[0]["parameters"]["navigatorItemGuid"] == NAV


async def test_empty_view_says_how_to_generate_it_and_rebuild_fills_it():
    fake = model(section_cut_needs_rebuild=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        empty = await tool.get_section_cut_elements(c, NAV, 19723)
        assert empty["elements"] == [] and "rebuild=true" in empty["note"]
        with pytest.raises(ValueError, match="no section elements"):
            await tool.create_section_dimensions(c, NAV, [floor_to_ceiling()], port=19723)
        rebuilt = await tool.get_section_cut_elements(c, NAV, 19723, rebuild=True)
    assert rebuilt["rebuilt"] and len(rebuilt["elements"]) == 4


async def test_preview_picks_top_and_bottom_nearest_station_and_sorts_by_height():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await tool.create_section_dimensions(c, NAV, [floor_to_ceiling(3.95)], FAVORITE)
    item = preview["items"][0]
    assert [p["element_guid"] for p in item["points"]] == [SLAB, FINISH, CEILING, WALL]
    assert item["segments_m"] == [0.03, 2.57, 0.2]
    witnesses = item["parameters"]["witnessPoints"]
    assert witnesses[0]["supplUnId"] == 1004  # slab top at x 4.0, the one nearest 3.95
    assert item["parameters"]["direction"] == {"x": 0.0, "y": 1.0}
    assert "CreateSectionDimensions" not in fake.own_addon_calls
    assert preview["dry_run"] is True


async def test_apply_needs_port_and_token_and_verifies_each_witness():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await tool.create_section_dimensions(c, NAV, [floor_to_ceiling()], FAVORITE)
        with pytest.raises(ValueError, match="explicit port"):
            await tool.create_section_dimensions(
                c, NAV, [floor_to_ceiling()], FAVORITE, None, False, preview["confirmation_token"]
            )
        receipt = await tool.create_section_dimensions(
            c, NAV, [floor_to_ceiling()], FAVORITE, 19723, False, preview["confirmation_token"]
        )
        assert receipt["status"] == "verified"
        sent = fake.own_addon_requests[-1]
        assert sent["command"] == "CreateSectionDimensions"
        assert sent["parameters"]["favorite"] == FAVORITE
        assert sent["parameters"]["navigatorItemGuid"] == NAV
        with pytest.raises(ValueError, match="already consumed"):
            await tool.create_section_dimensions(
                c, NAV, [floor_to_ceiling()], FAVORITE, 19723, False, preview["confirmation_token"]
            )


async def test_moved_witness_is_reported_not_hidden():
    fake = model(section_dimension_shift=0.05)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await tool.create_section_dimensions(c, NAV, [floor_to_ceiling()])
        receipt = await tool.create_section_dimensions(
            c, NAV, [floor_to_ceiling()], None, 19723, False, preview["confirmation_token"]
        )
    assert receipt["status"] == "needs_review"
    assert "witnessPoints.0.location.y" in receipt["items"][0]["mismatches"]


async def test_refuses_element_not_in_view_and_points_at_same_height():
    fake = model()
    other = "55555555-5555-4555-8555-555555555555"
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="not cut or seen"):
            await tool.create_section_dimensions(
                c,
                NAV,
                [{"station_x": 1, "points": [{"element_guid": SLAB, "at": "top"},
                                              {"element_guid": other, "at": "top"}]}],
            )  # fmt: skip
        with pytest.raises(ValueError, match="same height"):
            await tool.create_section_dimensions(
                c,
                NAV,
                [{"station_x": 1, "points": [{"element_guid": SLAB, "at": "top"},
                                              {"element_guid": FINISH, "at": "bottom"}]}],
            )  # fmt: skip


def test_repeated_point_is_refused():
    with pytest.raises(ValidationError, match="repeated"):
        tool.SectionDimension.model_validate(
            {"station_x": 0, "points": [{"element_guid": SLAB, "at": "top"}] * 2}
        )
