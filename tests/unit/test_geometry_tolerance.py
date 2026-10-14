"""Geometric verification must not become looser after translating the model."""

import json

import httpx
import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import meshes, write
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
GUID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


@pytest.mark.parametrize("origin", [0.0, 6500000.0, -6500000.0])
async def test_ignored_five_millimetre_move_is_never_verified(origin):
    box2 = {"xMin": origin, "yMin": origin, "xMax": origin + 4, "yMax": origin + 3}
    box3 = {**box2, "zMin": 0, "zMax": 3}
    fake = FakeArchicad(
        19723,
        elements={GUID: "Wall"},
        move_ignored=True,
        bounding_boxes_2d={GUID: {"boundingBox2D": box2}},
        bounding_boxes_3d={GUID: {"boundingBox3D": box3}},
    )
    change = [{"guid": GUID, "vector": {"x": 0.005, "y": 0, "z": 0}}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await write.move_elements(c, change, 19723)
        result = await write.move_elements(c, change, 19723, False, preview["confirmation_token"])
    assert result["items"][0]["status"] == "verification_failed"
    assert "2d.xMin" in result["items"][0]["mismatches"]


@pytest.mark.parametrize("origin", [0.0, 6500000.0, -6500000.0])
async def test_five_millimetre_wrong_mesh_vertex_is_rejected_at_every_origin(origin):
    fake = FakeArchicad(19723)
    outline = [
        {"x": origin, "y": origin, "z": 0},
        {"x": origin + 4, "y": origin, "z": 1},
        {"x": origin, "y": origin + 3, "z": 0},
    ]

    def handler(request):
        body = json.loads(request.content)
        response = fake.handle(body)
        cmd = body.get("parameters", {}).get("addOnCommandId", {}).get("commandName")
        if cmd == "CreateMeshes":
            for row in fake.details.values():
                row["details"]["polygonCoordinates"][1]["x"] += 0.005
        return httpx.Response(200, json=response)

    entries = [{"outline": outline, "floor_index": 0, "level": 0}]
    async with ArchicadClient(transport=httpx.MockTransport(handler)) as c:
        preview = await meshes.create_meshes(c, entries, 19723)
        result = await meshes.create_meshes(c, entries, 19723, False, preview["confirmation_token"])
    assert result["items"][0]["status"] == "verification_failed"
    assert "details.polygonCoordinates" in result["items"][0]["mismatches"]


@pytest.mark.parametrize("origin", [0.0, 6500000.0, -6500000.0])
async def test_valid_small_unclosed_polygon_is_not_mistaken_for_closed(origin):
    fake = FakeArchicad(19723)
    outline = [
        {"x": origin, "y": origin, "z": 0},
        {"x": origin + 0.001, "y": origin, "z": 0},
        {"x": origin + 0.001, "y": origin + 0.001, "z": 0},
        {"x": origin, "y": origin + 0.001, "z": 0},
    ]

    def handler(request):
        body = json.loads(request.content)
        response = fake.handle(body)
        cmd = body.get("parameters", {}).get("addOnCommandId", {}).get("commandName")
        if cmd == "CreateMeshes":
            for row in fake.details.values():
                # Both closed and unclosed equivalent boundaries are supported by the matcher.
                row["details"]["polygonCoordinates"].pop()
        return httpx.Response(200, json=response)

    entries = [{"outline": outline, "floor_index": 0, "level": 0}]
    async with ArchicadClient(transport=httpx.MockTransport(handler)) as c:
        preview = await meshes.create_meshes(c, entries, 19723)
        result = await meshes.create_meshes(c, entries, 19723, False, preview["confirmation_token"])
    assert result["status"] == "verified"


@pytest.mark.parametrize("origin", [0.0, 6500000.0, -6500000.0])
@pytest.mark.parametrize("error, expected", [(0.0005, "verified"), (0.002, "verification_failed")])
async def test_move_tolerance_stays_one_millimetre_in_every_coordinate_system(
    origin, error, expected
):
    box2 = {"xMin": origin, "yMin": 0, "xMax": origin + 4, "yMax": 3}
    fake = FakeArchicad(
        19723,
        elements={GUID: "Wall"},
        bounding_boxes_2d={GUID: {"boundingBox2D": box2}},
        bounding_boxes_3d={GUID: {"boundingBox3D": {**box2, "zMin": 0, "zMax": 3}}},
    )

    def handler(request):
        body = json.loads(request.content)
        response = fake.handle(body)
        cmd = body.get("parameters", {}).get("addOnCommandId", {}).get("commandName")
        if cmd == "MoveElements":
            for configured, key in (
                (fake.bounding_boxes_2d, "boundingBox2D"),
                (fake.bounding_boxes_3d, "boundingBox3D"),
            ):
                configured[GUID][key]["xMin"] += error
                configured[GUID][key]["xMax"] += error
        return httpx.Response(200, json=response)

    change = [{"guid": GUID, "vector": {"x": 1, "y": 0, "z": 0}}]
    async with ArchicadClient(transport=httpx.MockTransport(handler)) as c:
        preview = await write.move_elements(c, change, 19723)
        result = await write.move_elements(c, change, 19723, False, preview["confirmation_token"])
    assert result["items"][0]["status"] == expected
