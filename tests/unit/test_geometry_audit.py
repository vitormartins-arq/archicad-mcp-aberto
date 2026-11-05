"""Bounding-box triage via the existing documented fixture; no live Archicad."""

import json
from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import AmbiguousTarget, ArchicadClient
from archicad_mcp_aberto.server import create_server
from archicad_mcp_aberto.tools import geometry_audit
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
A = "AAAAAAAA-AAAA-AAAA-AAAA-AAAAAAAAAAAA"
B = "BBBBBBBB-BBBB-BBBB-BBBB-BBBBBBBBBBBB"
C = "CCCCCCCC-CCCC-CCCC-CCCC-CCCCCCCCCCCC"
D = "DDDDDDDD-DDDD-DDDD-DDDD-DDDDDDDDDDDD"


def box(x0=0, x1=1, y0=0, y1=1, z0=0, z1=1):
    return {"boundingBox3D": dict(xMin=x0, xMax=x1, yMin=y0, yMax=y1, zMin=z0, zMax=z1)}


def client(*instances):
    return ArchicadClient(ports=(19723, 19724), transport=fake_transport(*instances))


async def test_one_official_batch_no_tapir_no_mutation_and_only_findings():
    fake = FakeArchicad(19723, elements={A: "Wall", B: "Object", C: "Slab"}, tapir_version=None)
    fake.bounding_boxes_3d = {A: box(), B: box(20000, 20001), C: box(z1=0)}
    before = deepcopy((fake.elements, fake.bounding_boxes_3d, fake.selection))
    async with client(fake) as c:
        result = await geometry_audit.audit_geometry(c, [A, B, C])
    assert fake.calls == ["API.GetProductInfo", "API.Get3DBoundingBoxes"]
    assert fake.tapir_calls == []
    assert (fake.elements, fake.bounding_boxes_3d, fake.selection) == before
    assert result["summary"] == {
        "checked": 3,
        "with_findings": 1,
        "without_findings": 2,
        "by_code": {"far_from_origin": 1},
    }
    assert [r["guid"] for r in result["findings"]] == [B]
    assert result["findings"][0]["min_distance_to_origin_m"] == 20000


async def test_pagination_counts_the_entire_batch_and_preserves_unavailable():
    fake = FakeArchicad(19723, elements={A: "Object", B: "Wall", C: "Object"})
    fake.bounding_boxes_3d = {A: box(0, 0, 0, 0, 0, 0), B: box(0, 501), C: box()}
    async with client(fake) as c:
        first = await geometry_audit.audit_geometry(c, [A, B, C, D], limit=1)
        last = await geometry_audit.audit_geometry(c, [A, B, C, D], offset=2, limit=1)
        after = await geometry_audit.audit_geometry(c, [A, B, C, D], offset=10)
    assert first["summary"] == last["summary"] == after["summary"]
    assert first["summary"]["with_findings"] == 3
    assert first["has_more"] and first["next_offset"] == 1
    assert first["findings"][0]["issues"] == [{"code": "zero_size_bounds"}]
    assert last["findings"][0]["guid"] == D
    assert last["findings"][0]["issues"][0]["code"] == "bounds_unavailable"
    assert "error" in last["findings"][0]["issues"][0]
    assert not last["has_more"] and last["next_offset"] is None
    assert after["findings"] == [] and not after["has_more"]


async def test_duplicate_guids_are_canonicalized_before_the_single_batch(monkeypatch):
    fake = FakeArchicad(19723, elements={A: "Wall"})
    seen = []
    async with client(fake) as c:
        original = c.command

        async def record(port, command, parameters=None, **kwargs):
            if command == "Get3DBoundingBoxes":
                seen.extend(parameters["elements"])
            return await original(port, command, parameters, **kwargs)

        monkeypatch.setattr(c, "command", record)
        result = await geometry_audit.audit_geometry(c, [A.lower(), A] * 250)
    assert seen == [{"elementId": {"guid": A}}]
    assert result["summary"]["checked"] == 1
    assert result["duplicate_inputs_ignored"] == 499


@pytest.mark.parametrize("value", [0, -1, True, "500", float("nan"), float("inf"), 10**1000])
@pytest.mark.parametrize("name", ["max_origin_distance_m", "max_extent_m"])
async def test_invalid_thresholds_fail_before_any_request(value, name):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        with pytest.raises(ValueError, match=name):
            await geometry_audit.audit_geometry(c, [A], **{name: value})
    assert fake.calls == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"offset": -1},
        {"offset": True},
        {"offset": 0.5},
        {"limit": 0},
        {"limit": 501},
        {"limit": True},
    ],
)
async def test_invalid_pagination_before_any_request(kwargs):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        with pytest.raises(ValueError):
            await geometry_audit.audit_geometry(c, [A], **kwargs)
    assert fake.calls == []


@pytest.mark.parametrize("guids", [[], [A] * 501, [A, "bad-guid"]])
async def test_input_scope_is_bounded_and_fails_before_requests(guids):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        with pytest.raises(ValueError):
            await geometry_audit.audit_geometry(c, guids)
    assert fake.calls == []


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "1", None, 10**1000])
async def test_invalid_api_coordinates_never_leak_nonfinite_json(bad, monkeypatch):
    fake = FakeArchicad(19723, elements={A: "Wall"})
    async with client(fake) as c:
        original = c.command

        async def faulty(port, command, parameters=None, **kwargs):
            if command == "Get3DBoundingBoxes":
                return {"boundingBoxes3D": [box(x0=bad)]}
            return await original(port, command, parameters, **kwargs)

        monkeypatch.setattr(c, "command", faulty)
        result = await geometry_audit.audit_geometry(c, [A])
    assert result["summary"]["by_code"] == {"invalid_bounds": 1}
    assert "bounds" not in result["findings"][0]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("bounds", [box(2, 1), box(-1e308, 1e308)])
async def test_inverted_and_overflowing_extents_are_reported(bounds):
    fake = FakeArchicad(19723, elements={A: "Wall"}, bounding_boxes_3d={A: bounds})
    async with client(fake) as c:
        result = await geometry_audit.audit_geometry(c, [A])
    assert result["summary"]["by_code"] == {"invalid_bounds": 1}
    json.dumps(result, allow_nan=False)


async def test_nearest_point_not_box_center_and_exact_threshold_is_clear():
    fake = FakeArchicad(19723, elements={A: "Wall", B: "Wall", C: "Wall"})
    fake.bounding_boxes_3d = {A: box(-20000, 20000), B: box(-20001, -20000), C: box(20000, 20001)}
    async with client(fake) as c:
        result = await geometry_audit.audit_geometry(
            c, [A, B, C], max_origin_distance_m=20000, max_extent_m=40000
        )
    assert result["findings"] == []


async def test_ambiguous_target_and_explicit_port():
    first, second = FakeArchicad(19723), FakeArchicad(19724, elements={A: "Wall"})
    async with client(first, second) as c:
        with pytest.raises(AmbiguousTarget):
            await geometry_audit.audit_geometry(c, [A])
    assert first.calls == second.calls == ["API.GetProductInfo"]
    first.calls.clear()
    second.calls.clear()
    async with client(first, second) as c:
        result = await geometry_audit.audit_geometry(c, [A], port=19724)
    assert result["port"] == 19724 and not first.calls


async def test_bad_cardinality_cannot_assign_a_box_to_the_wrong_guid(monkeypatch):
    fake = FakeArchicad(19723)
    async with client(fake) as c:
        original = c.command

        async def faulty(port, command, parameters=None, **kwargs):
            if command == "Get3DBoundingBoxes":
                return {"boundingBoxes3D": []}
            return await original(port, command, parameters, **kwargs)

        monkeypatch.setattr(c, "command", faulty)
        with pytest.raises(ValueError, match="cardinality"):
            await geometry_audit.audit_geometry(c, [A, B])


async def test_tool_is_read_only_and_requires_an_explicit_scope():
    tool = next(t for t in await create_server().list_tools() if t.name == "audit_geometry")
    assert tool.annotations.readOnlyHint and not tool.annotations.openWorldHint
    assert tool.inputSchema["required"] == ["element_guids"]
    assert tool.inputSchema["properties"]["limit"]["default"] == 20
