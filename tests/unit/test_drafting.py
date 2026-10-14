import math

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import drafting
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
STORIES = [
    {"index": 0, "name": "Térreo", "level": 0.0},
    {"index": 1, "name": "Superior", "level": 3.0},
]
SQUARE = [{"x": 0, "y": 0}, {"x": 4, "y": 0}, {"x": 4, "y": 3}, {"x": 0, "y": 3}]
TIJOLO = "55555555-5555-4555-8555-555555555552"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    return FakeArchicad(
        19723, stories=[dict(s) for s in STORIES], layers={1: "Walls", 7: "Desenho"}, **kwargs
    )


async def apply(tool, c, inputs):
    preview = await tool(c, inputs, 19723)
    return await tool(c, inputs, 19723, False, preview["confirmation_token"])


def sent(fake, command, key):
    return next(r for r in fake.tapir_requests if r["command"] == command)["parameters"][key]


def line(**changes):
    return {"start": {"x": 0, "y": 0}, "end": {"x": 5, "y": 0}, "floor_index": 0, **changes}


def polyline(**changes):
    return {"points": [*SQUARE, SQUARE[0]], "floor_index": 1, **changes}


def arc(**changes):
    return {
        "center": {"x": 1, "y": 1},
        "radius": 2,
        "start_angle": 0,
        "end_angle": math.pi / 2,
        "floor_index": 0,
        **changes,
    }


def circle(**changes):
    return {"center": {"x": 1, "y": 1}, "radius": 0.5, "floor_index": 0, **changes}


def fill(**changes):
    return {"outline": SQUARE, "floor_index": 0, **changes}


CASES = [
    (drafting.create_lines, "CreateLineElements", "linesData", line),
    (drafting.create_polylines, "CreatePolylines", "polylinesData", polyline),
    (drafting.create_arcs, "CreateArcs", "arcsData", arc),
    (drafting.create_circles, "CreateCircles", "circlesData", circle),
    (drafting.create_fills, "CreateHatches", "hatchesData", fill),
]


@pytest.mark.parametrize(("tool", "command", "key", "make"), CASES)
async def test_preview_then_apply(tool, command, key, make):
    fake = model()
    inputs = [make(layer="desenho", pen=5)]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await tool(c, inputs, 19723)
        assert command not in fake.tapir_calls
        assert preview["items"][0]["layerName"] == "Desenho"
        token = preview["confirmation_token"]
        result = await tool(c, inputs, 19723, False, token)
        with pytest.raises(ValueError, match="consumed"):
            await tool(c, inputs, 19723, False, token)
    assert result["status"] == "verified", result["items"][0].get("mismatches")
    payload = sent(fake, command, key)[0]
    assert payload["layerIndex"] == 7
    assert payload["fillPenIndex" if command == "CreateHatches" else "linePenIndex"] == 5
    assert payload["floorInd"] == inputs[0]["floor_index"]


@pytest.mark.parametrize(("tool", "command", "key", "make"), CASES)
async def test_defaults_are_left_to_the_tool(tool, command, key, make):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(tool, c, [make()])
    assert result["status"] == "verified"
    payload = sent(fake, command, key)[0]
    for absent in ("layerIndex", "linePenIndex", "fillPenIndex", "fillId", "contourPenIndex"):
        assert absent not in payload


async def test_payload_shapes():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        await apply(drafting.create_lines, c, [line()])
        await apply(drafting.create_arcs, c, [arc()])
        await apply(drafting.create_fills, c, [fill(outline=[*SQUARE, SQUARE[0]], contour_pen=3)])
    assert sent(fake, "CreateLineElements", "linesData")[0] == {
        "floorInd": 0,
        "begCoordinate": {"x": 0, "y": 0},
        "endCoordinate": {"x": 5, "y": 0},
    }
    assert sent(fake, "CreateArcs", "arcsData")[0] == {
        "floorInd": 0,
        "origin": {"x": 1, "y": 1},
        "radius": 2,
        "begAngle": 0,
        "endAngle": math.pi / 2,
    }
    hatch = sent(fake, "CreateHatches", "hatchesData")[0]
    assert len(hatch["coordinates"]) == 4 and hatch["contourPenIndex"] == 3


async def test_fill_by_name():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await drafting.create_fills(c, [fill(fill="tijolo")], 19723)
        assert preview["items"][0]["fillName"] == "Tijolo"
        result = await drafting.create_fills(
            c, [fill(fill="tijolo")], 19723, False, preview["confirmation_token"]
        )
        with pytest.raises(ValueError, match="ambiguous"):
            await drafting.create_fills(c, [fill(fill="Concreto")], 19723)
        with pytest.raises(ValueError, match="does not exist"):
            await drafting.create_fills(c, [fill(fill="Madeira")], 19723)
    assert result["status"] == "verified"
    assert sent(fake, "CreateHatches", "hatchesData")[0]["fillId"] == {"guid": TIJOLO}


async def test_unknown_layer_and_story_refused():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="Layer 'Cotas' does not exist"):
            await drafting.create_lines(c, [line(layer="Cotas")], 19723)
        with pytest.raises(ValueError, match="story 9"):
            await drafting.create_circles(c, [circle(floor_index=9)], 19723)
    assert not set(fake.tapir_calls) & {"CreateLineElements", "CreateCircles"}


@pytest.mark.parametrize(
    ("tool", "make"), [(drafting.create_polylines, polyline), (drafting.create_fills, fill)]
)
async def test_coordinates_checked_without_2d_boxes(tool, make):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(tool, c, [make()])
    assert result["items"][0]["status"] == "verified"
    assert "API.Get2DBoundingBoxes" not in fake.calls
    fake = model(drafting_coordinate_shift=0.01)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(tool, c, [make()])
    item = result["items"][0]
    assert item["status"] == "verification_failed"
    assert item["mismatches"] == ["details.coordinates"]


async def test_circle_read_back_as_full_arc():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(drafting.create_circles, c, [circle()])
        assert result["items"][0]["status"] == "verified"
        for row in fake.details.values():
            row["details"]["endAngle"] = 1.0
        preview = await drafting.create_circles(c, [circle()], 19723)
        original = fake._tapir

        def half(params):
            response = original(params)
            for row in fake.details.values():
                row["details"]["endAngle"] = math.pi
            return response

        fake._tapir = half
        result = await drafting.create_circles(
            c, [circle()], 19723, False, preview["confirmation_token"]
        )
    assert result["items"][0]["mismatches"] == ["type"]


async def test_arc_angle_on_the_circle_and_wrong_geometry():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await drafting.create_arcs(c, [arc(end_angle=-3 * math.pi / 2)], 19723)
        original = fake._tapir

        def stored(params):
            response = original(params)
            for row in fake.details.values():
                if row["type"] == "Arc":
                    row["details"]["endAngle"] = math.pi / 2
                    row["details"]["radius"] = 2.1
            return response

        fake._tapir = stored
        result = await drafting.create_arcs(
            c, [arc(end_angle=-3 * math.pi / 2)], 19723, False, preview["confirmation_token"]
        )
    assert result["items"][0]["mismatches"] == ["details.radius"]


@pytest.mark.parametrize(
    ("tool", "item"),
    [
        (drafting.create_lines, line(end={"x": 0, "y": 0})),
        (drafting.create_lines, line(pen=0)),
        (drafting.create_lines, line(pen=256)),
        (drafting.create_lines, line(layer="")),
        (drafting.create_lines, line(color="red")),
        (drafting.create_polylines, polyline(points=[{"x": 0, "y": 0}])),
        (drafting.create_polylines, polyline(points=[{"x": 0, "y": 0}, {"x": 0, "y": 0}])),
        (drafting.create_arcs, arc(end_angle=2 * math.pi)),
        (drafting.create_arcs, arc(radius=0)),
        (drafting.create_circles, circle(radius=-1)),
        (drafting.create_fills, fill(outline=SQUARE[:2])),
        (
            drafting.create_fills,
            fill(outline=[{"x": 0, "y": 0}, {"x": 4, "y": 4}, {"x": 4, "y": 0}, {"x": 0, "y": 4}]),
        ),
        (drafting.create_fills, fill(fill="")),
    ],
)
async def test_invalid_inputs_refused_before_network(tool, item):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await tool(c, [item])
    assert not fake.calls


async def test_limits_partial_error_lost_response_and_port():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await drafting.create_lines(c, [])
        with pytest.raises(ValueError):
            await drafting.create_lines(c, [line()] * 51)
        preview = await drafting.create_lines(c, [line()])
        with pytest.raises(ValueError, match="explicit port"):
            await drafting.create_lines(c, [line()], None, False, preview["confirmation_token"])
    error = {"error": {"code": -1, "message": "Failed to create element."}}
    fake = model(create_errors={0: error})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(drafting.create_fills, c, [fill(), fill()])
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]
    fake = model(lose_drafting_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(drafting.create_circles, c, [circle()])
    assert result["items"][0]["status"] == "unknown"
    assert fake.tapir_calls.count("CreateCircles") == 1
