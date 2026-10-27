"""Grid lines through the ArchicadMcpAberto add-on, against the simulated Archicad."""

import math

import pytest
from pydantic import ValidationError

from archicad_mcp_aberto.connection import AddOnError, ArchicadClient
from archicad_mcp_aberto.tools import grids
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


STORIES = [{"index": 0, "name": "Térreo", "level": 0.0}, {"index": 1, "name": "1º", "level": 3.0}]


def model(**kwargs):
    return FakeArchicad(
        19723, stories=[dict(s) for s in STORIES], layers={1: "Walls", 7: "Desenho"}, **kwargs
    )


def line(**changes):
    return {"start": {"x": 0.0, "y": 0.0}, "end": {"x": 0.0, "y": 12.5}, "floor_index": 0,
            **changes}  # fmt: skip


async def apply(c, items):
    preview = await grids.create_grid_elements(c, items, 19723)
    return preview, await grids.create_grid_elements(
        c, items, 19723, False, preview["confirmation_token"]
    )


async def test_grid_lines_are_drawn_in_one_call_and_read_back():
    fake = model()
    items = [
        line(parameters=[{"name": "AC_MarkerText", "value": "A"}]),
        line(start={"x": 6.0, "y": 0.0}, end={"x": 0.0, "y": 0.0}, layer="desenho",
             parameters=[{"name": "ac_bubbleboth", "value": True}]),
    ]  # fmt: skip
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview, result = await apply(c, items)
        listed = await grids.list_grid_elements(c, 19723)
    assert preview["items"][1]["parameters"]["parameters"] == [
        {"name": "AC_BubbleBoth", "value": True}
    ]
    assert math.isclose(preview["items"][1]["angle"], math.pi)
    assert [i["status"] for i in result["items"]] == ["verified", "verified"]
    assert fake.own_addon_calls.count("CreateGridElements") == 1
    assert listed["count"] == 2
    second = next(r for r in listed["grid_elements"] if r["start"]["x"] == 6.0)
    assert math.isclose(second["end"]["x"], 0.0, abs_tol=1e-9)
    assert "parameters" not in second


async def test_dropped_parameter_is_caught():
    fake = model(grid_ignored={"AC_MarkerText"})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [line(parameters=[{"name": "AC_MarkerText", "value": "B"}])])
    assert result["items"][0]["mismatches"] == ["parameter AC_MarkerText"]


async def test_item_error_fails_only_that_line():
    fake = model(grid_create_errors={0: {"code": -1, "message": "item 0: no"}})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        _, result = await apply(c, [line(), line(floor_index=1)])
    assert [i["status"] for i in result["items"]] == ["failed", "verified"]


async def test_preview_refusals():
    async with ArchicadClient(transport=fake_transport(model())) as c:
        for params, match in (
            ([{"name": "Nope", "value": 1.0}], "no parameter"),
            ([{"name": "AC_MarkerText", "value": 1.0}], "needs text"),
            ([{"name": "AC_BubbleSize", "value": "big"}], "number or boolean"),
            ([{"name": "AC_Points", "value": 1.0}], "cannot be set"),
            ([{"name": "AC_Pen", "value": 1.0}], "cannot be set"),
        ):
            with pytest.raises(ValueError, match=match):
                await grids.create_grid_elements(c, [line(parameters=params)], 19723)
        with pytest.raises(ValueError, match="story 9"):
            await grids.create_grid_elements(c, [line(floor_index=9)], 19723)
        with pytest.raises(ValueError, match="Layer"):
            await grids.create_grid_elements(c, [line(layer="Inexistente")], 19723)
    for bad in (
        line(end={"x": 0.0, "y": 0.0}),
        line(parameters=[{"name": "AC_Length", "value": 3.0}]),
        line(parameters=[{"name": "X", "value": 1.0}, {"name": "x", "value": 2.0}]),
    ):
        with pytest.raises(ValidationError):
            grids.GridCreate.model_validate(bad)


async def test_tool_defaults_come_with_parameters():
    async with ArchicadClient(transport=fake_transport(model())) as c:
        listed = await grids.list_grid_elements(c, 19723, include_parameters=True)
    names = [p["name"] for p in listed["tool_defaults"]["parameters"]]
    assert "AC_MarkerText" in names and "start" not in listed["tool_defaults"]


async def test_missing_addon_says_how_to_install():
    fake = model(own_addon_loaded=False)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(AddOnError, match="Add-On Manager"):
            await grids.list_grid_elements(c, 19723)
        with pytest.raises(AddOnError, match="Add-On Manager"):
            await grids.create_grid_elements(c, [line()], 19723)
