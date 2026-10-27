"""create_associative_dimensions (Tapir 1.7.0), against the simulated Archicad."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import wall_dimensions
from tests.unit.fake_archicad import CREATE_WALLS_FIXTURE, FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
A = "3C3C3C3C-0000-4000-8000-00000000000A"
B = "3C3C3C3C-0000-4000-8000-00000000000B"
STORIES = [{"index": 0, "name": "Térreo", "level": 0.0}, {"index": 1, "name": "1º", "level": 3.0}]


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def wall(beg, end, floor=0, **details):
    row = deepcopy(CREATE_WALLS_FIXTURE["wall_details"])
    row["floorIndex"] = floor
    row["details"].update(begCoordinate=beg, endCoordinate=end, **details)
    return row


def model(**kwargs):
    fake = FakeArchicad(19723, stories=deepcopy(STORIES), elements={A: "Wall", B: "Wall"}, **kwargs)
    fake.details[A] = wall({"x": 0.0, "y": 0.0}, {"x": 4.0, "y": 0.0})
    fake.details[B] = wall({"x": 7.0, "y": 0.0}, {"x": 11.0, "y": 0.0})
    return fake


def dimension(**changes):
    return {
        "points": [{"wall_guid": A, "end": "end"}, {"wall_guid": B.lower(), "end": "start"}],
        "reference_point": {"x": 0, "y": 2},
        **changes,
    }


async def apply(c, items):
    tool = wall_dimensions.create_associative_dimensions
    preview = await tool(c, items, 19723)
    return preview, await tool(c, items, 19723, False, preview["confirmation_token"])


def sent(fake):
    request = next(r for r in fake.tapir_requests if r["command"] == "CreateAssociativeDimensions")
    return request["parameters"]["dimensionsData"]


async def test_dimension_between_wall_ends_is_verified_point_by_point():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(c, [dimension()])
    assert [(w["x"], w["y"]) for w in preview["items"][0]["witnesses"]] == [(4.0, 0.0), (7.0, 0.0)]
    assert sent(fake) == [
        {
            "referencePoint": {"x": 0.0, "y": 2.0},
            "direction": {"x": 1.0, "y": 0.0},
            "floorIndex": 0,
            "witnessPoints": [
                {"elementId": {"guid": A}, "inIndex": 2},
                {"elementId": {"guid": B}, "inIndex": 1},
            ],
        }
    ]
    item = result["items"][0]
    assert item["status"] == "verified"
    assert len(item["dimension_data"]["witnessPoints"]) == 2


async def test_given_direction_is_sent():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        await apply(c, [dimension(direction={"x": 0, "y": 1})])
    assert sent(fake)[0]["direction"] == {"x": 0.0, "y": 1.0}


async def test_moved_witness_point_fails_verification():
    fake = model(dimension_witness_shift=0.01)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [dimension()])
    item = result["items"][0]
    assert item["status"] == "verification_failed"
    assert item["mismatches"] == ["witnessPoints.0.coordinate", "witnessPoints.1.coordinate"]


async def test_wrong_story_fails_verification():
    fake = model(dimension_floor_shift=1)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [dimension()])
    assert result["items"][0]["status"] == "verification_failed"
    assert "floorIndex" in result["items"][0]["mismatches"]


@pytest.mark.parametrize(
    ("setup", "message"),
    [
        (lambda f: f.details[B].update(floorIndex=1), "same story"),
        (lambda f: f.details[B]["details"].update(geometryType="Arc", arcAngle=1.0), "curved"),
        (
            lambda f: f.elements.update({B: "Slab"}) or f.details[B].update(type="Slab"),
            "not a wall",
        ),
    ],
)
async def test_refused_in_preview(setup, message):
    fake = model()
    setup(fake)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match=message):
            await wall_dimensions.create_associative_dimensions(c, [dimension()], 19723)
    assert "CreateAssociativeDimensions" not in [r["command"] for r in fake.tapir_requests]


async def test_repeated_end_refused():
    fake = model()
    points = [{"wall_guid": A, "end": "end"}, {"wall_guid": A, "end": "end"}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="repeated"):
            await wall_dimensions.create_associative_dimensions(
                c, [dimension(points=points)], 19723
            )


async def test_zero_length_first_wall_needs_direction():
    fake = model()
    fake.details[A]["details"]["endCoordinate"] = {"x": 0.0, "y": 0.0}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="give a direction"):
            await wall_dimensions.create_associative_dimensions(c, [dimension()], 19723)


@pytest.mark.parametrize(
    "bad",
    [
        {"points": [{"wall_guid": A, "end": "end"}]},
        {"points": [{"wall_guid": A, "end": "middle"}, {"wall_guid": B, "end": "end"}]},
        {"reference_point": None},
    ],
)
def test_invalid_input_refused(bad):
    with pytest.raises(ValidationError):
        wall_dimensions.WallPointsDimension.model_validate(dimension(**bad))


async def test_count_limits():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="between 1 and 50"):
            await wall_dimensions.create_associative_dimensions(c, [])
