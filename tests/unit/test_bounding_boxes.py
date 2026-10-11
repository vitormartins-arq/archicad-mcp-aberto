"""Official bounding box tools tested only through MockTransport."""

from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import AmbiguousTarget, ArchicadClient
from archicad_mcp_aberto.server import create_server
from archicad_mcp_aberto.tools import read
from tests.unit.fake_archicad import BOUNDING_BOXES_FIXTURE, FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
A = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
B = "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"
MISSING = "CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC"


def client(*instances):
    return ArchicadClient(ports=(19723, 19724), transport=fake_transport(*instances))


@pytest.mark.parametrize("mode", ["2d", "3d"])
async def test_boxes_in_metres_without_tapir(mode):
    fake = FakeArchicad(19723, elements={A: "Wall"}, tapir_version=None)
    before = deepcopy(fake.elements)
    async with client(fake) as c:
        result = await read.get_bounding_boxes(c, [A.lower()], mode=mode)
    dim = mode.upper()
    expected = BOUNDING_BOXES_FIXTURE[mode][f"boundingBoxes{dim}"][0][f"boundingBox{dim}"]
    assert result == {"port": 19723, "mode": mode, "boundingBoxes": [{"guid": A, "box": expected}]}
    assert fake.calls == ["API.GetProductInfo", f"API.Get{dim}BoundingBoxes"]
    assert fake.tapir_calls == [] and fake.elements == before


async def test_default_mode_is_2d_and_per_element_errors_preserve_order():
    fake = FakeArchicad(19723, elements={A: "Wall", B: "Slab"})
    async with client(fake) as c:
        result = await read.get_bounding_boxes(c, [A, MISSING, B])
    rows = result["boundingBoxes"]
    assert result["mode"] == "2d"
    assert [row["guid"] for row in rows] == [A, MISSING, B]
    assert "box" in rows[0] and "box" in rows[2]
    assert rows[1]["error"] == BOUNDING_BOXES_FIXTURE["error"]["error"]


@pytest.mark.parametrize("size", [0, 501])
async def test_bounds_rejected_before_requests(size):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        with pytest.raises(ValueError, match="between 1 and 500"):
            await read.get_bounding_boxes(c, [A] * size)
    assert fake.calls == []


async def test_accepts_500_and_preserves_duplicate_inputs():
    fake = FakeArchicad(19723, elements={A: "Wall"})
    async with client(fake) as c:
        result = await read.get_bounding_boxes(c, [A] * 500)
    assert len(result["boundingBoxes"]) == 500
    assert all(row["guid"] == A for row in result["boundingBoxes"])


@pytest.mark.parametrize("mode", ["2d", "3d"])
async def test_ambiguous_target_refused(mode):
    first, second = FakeArchicad(19723), FakeArchicad(19724)
    async with client(first, second) as c:
        with pytest.raises(AmbiguousTarget):
            await read.get_bounding_boxes(c, [A], mode=mode)
    assert first.calls == second.calls == ["API.GetProductInfo"]


async def test_explicit_port_reaches_only_selected_instance():
    first = FakeArchicad(19723)
    second = FakeArchicad(19724, elements={A: "Wall"})
    async with client(first, second) as c:
        result = await read.get_bounding_boxes(c, [A], port=19724)
    assert result["port"] == 19724 and "box" in result["boundingBoxes"][0]
    assert first.calls == []


@pytest.mark.parametrize("mode", ["4d", "2D", "", None])
async def test_invalid_mode_before_requests(mode):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        with pytest.raises(ValueError, match="mode"):
            await read.get_bounding_boxes(c, [A], mode=mode)
    assert fake.calls == []


async def test_invalid_guid_before_requests():
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        with pytest.raises(ValueError):
            await read.get_bounding_boxes(c, [A, "bad"])
    assert fake.calls == []


async def test_cardinality_mismatch_does_not_assign_wrong_guid(monkeypatch):
    fake = FakeArchicad(19723, elements={A: "Wall"})
    async with client(fake) as c:
        original = c.command

        async def faulty(port, command, parameters=None, **kwargs):
            result = await original(port, command, parameters, **kwargs)
            return {"boundingBoxes2D": []} if command == "Get2DBoundingBoxes" else result

        monkeypatch.setattr(c, "command", faulty)
        with pytest.raises(ValueError, match="cardinality"):
            await read.get_bounding_boxes(c, [A])


async def test_read_only_registration_and_documented_fixture():
    tool = next(t for t in await create_server().list_tools() if t.name == "get_bounding_boxes")
    assert tool.annotations.readOnlyHint and not tool.annotations.openWorldHint
    assert tool.inputSchema["properties"]["mode"]["default"] == "2d"
    assert "element_ids" in tool.inputSchema["required"]
    assert BOUNDING_BOXES_FIXTURE["provenance"]["live_capture"] is False
