"""Simple terrain creation and metadata edits, only with MockTransport."""

import json
from copy import deepcopy

import httpx
import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import meshes, write
from tests.unit.fake_archicad import MESHES_FIXTURE, FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
GUID = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
OUTLINE = [
    {"x": 0, "y": 0, "z": 10},
    {"x": 4, "y": 0, "z": 10.5},
    {"x": 4, "y": 3, "z": 11},
    {"x": 0, "y": 3, "z": 10.5},
]
INPUT = {"outline": OUTLINE, "floor_index": 1, "level": 10}
STORIES = [{"index": 0, "name": "Ground", "level": 0}, {"index": 1, "name": "Upper", "level": 3}]


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    return FakeArchicad(19723, stories=deepcopy(STORIES), **kwargs)


def existing(**kwargs):
    fake = model(elements={GUID: "Mesh", OTHER: "Mesh"}, **kwargs)
    fake.details = {g: deepcopy(MESHES_FIXTURE["mesh_details"]) for g in (GUID, OTHER)}
    return fake


async def apply(c, entries, edit=False):
    tool = meshes.modify_meshes if edit else meshes.create_meshes
    preview = await tool(c, entries, 19723)
    return await tool(c, entries, 19723, False, preview["confirmation_token"])


async def test_absolute_heights_on_upper_story_preview_and_apply():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await meshes.create_meshes(c, [INPUT], 19723)
        item = preview["items"][0]
        assert item["outline_absolute"] == OUTLINE and item["base_plane_level"] == 10
        assert item["parameters"]["level"] == 7
        assert [p["z"] for p in item["parameters"]["polygonCoordinates"]] == [0, 0.5, 1, 0.5]
        assert "CreateMeshes" not in fake.tapir_calls and fake.elements == {}
        result = await meshes.create_meshes(c, [INPUT], 19723, False, preview["confirmation_token"])
        with pytest.raises(ValueError, match="consumed"):
            await meshes.create_meshes(c, [INPUT], 19723, False, preview["confirmation_token"])
    assert result["status"] == "verified"
    item = result["items"][0]
    assert item["mesh_receipt_id"] and item["after"]["floorIndex"] == 1
    assert item["after"]["details"]["level"] == 7
    assert (
        item["after"]["details"]["polygonCoordinates"][-1]
        == item["after"]["details"]["polygonCoordinates"][0]
    )
    payload = next(r["parameters"] for r in fake.tapir_requests if r["command"] == "CreateMeshes")
    assert list(payload) == ["meshesData"]
    assert payload["meshesData"][0]["skirtType"] == "SurfaceOnlyWithoutSkirt"
    assert payload["meshesData"][0]["holes"] == payload["meshesData"][0]["polygonArcs"] == []
    assert not any("Save" in cmd or "Delete" in cmd for cmd in fake.tapir_calls)


@pytest.mark.parametrize("kind", ["WithSkirt", "SolidBodyWithSkirt"])
async def test_supported_skirt_modes_and_display_fields(kind):
    fake = model()
    entry = {
        **INPUT,
        "skirt_type": kind,
        "skirt_depth": 2,
        "ridges": "UserDefined",
        "show_lines": False,
    }
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [entry])
    assert result["status"] == "verified"
    d = result["items"][0]["after"]["details"]
    assert d["skirtType"] == kind and d["skirtLevel"] == 2
    assert d["ridges"] == "UserDefined" and d["showLines"] is False


async def test_closing_repeat_normalized_before_send():
    fake = model()
    entry = {**INPUT, "outline": OUTLINE + [OUTLINE[0]]}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [entry])
    assert result["status"] == "verified"
    assert len(result["items"][0]["parameters"]["polygonCoordinates"]) == 4


@pytest.mark.parametrize(
    "outline",
    [
        OUTLINE[:2],
        OUTLINE + [{**OUTLINE[0], "z": 9}],
        [
            {"x": 0, "y": 0, "z": 0},
            {"x": 2, "y": 2, "z": 0},
            {"x": 0, "y": 2, "z": 0},
            {"x": 2, "y": 0, "z": 0},
        ],
        [{"x": 0, "y": 0, "z": 0}, {"x": 1, "y": 0, "z": 1}, {"x": 2, "y": 0, "z": 2}],
        OUTLINE + [OUTLINE[1]],
        [{**OUTLINE[0], "z": float("nan")}, *OUTLINE[1:]],
    ],
)
async def test_invalid_geometry_refused_before_network(outline):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await meshes.create_meshes(c, [{**INPUT, "outline": outline}])
    assert not fake.calls


@pytest.mark.parametrize(
    "override",
    [
        {"skirt_type": "SolidBodyWithSkirt", "skirt_depth": 0},
        {"skirt_depth": -1},
        {"skirt_type": "unknown"},
        {"ridges": "unknown"},
        {"holes": []},
        {"sublines": []},
        {"level": float("inf")},
        {"show_lines": 1},
    ],
)
async def test_unsupported_or_invalid_inputs_refused(override):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await meshes.create_meshes(c, [{**INPUT, **override}])
    assert not fake.calls


async def test_solid_bottom_above_a_boundary_vertex_refused():
    fake = model()
    entry = {
        **INPUT,
        "skirt_type": "SolidBodyWithSkirt",
        "skirt_depth": 1,
        "outline": [{**OUTLINE[0], "z": 8}, *OUTLINE[1:]],
    }
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="bottom"):
            await meshes.create_meshes(c, [entry])
    assert not fake.calls


async def test_surface_allows_negative_vertex_offsets():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [{**INPUT, "level": 12}])
    assert result["status"] == "verified"
    assert result["items"][0]["parameters"]["polygonCoordinates"][0]["z"] == -2


@pytest.mark.parametrize("entries", [[], [INPUT] * 21])
async def test_creation_limits_before_network(entries):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await meshes.create_meshes(c, entries)
    assert not fake.calls


async def test_missing_story_refused():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="story"):
            await meshes.create_meshes(c, [{**INPUT, "floor_index": 99}], 19723)
    assert "CreateMeshes" not in fake.tapir_calls


async def test_twenty_meshes_and_partial_native_failure():
    fake = model(create_errors={1: MESHES_FIXTURE["create_error"]})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [INPUT] * 20)
    assert result["counts"]["verified"] == 19 and result["counts"]["failed"] == 1
    assert result["items"][1]["error"]["code"] == -1
    assert fake.tapir_calls.count("CreateMeshes") == 1


async def test_ignored_base_change_fails_verification():
    fake = model(mesh_base_shift=1)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [INPUT])
    assert result["items"][0]["status"] == "verification_failed"
    assert "details.level" in result["items"][0]["mismatches"]


@pytest.mark.parametrize("transform", ["reverse", "shift", "wrong-z", "hole"])
async def test_polygon_verification_preserves_xyz_but_accepts_winding_and_start(transform):
    fake = model()

    def handler(request):
        body = json.loads(request.content)
        response = fake.handle(body)
        command = body.get("parameters", {}).get("addOnCommandId", {}).get("commandName")
        if command == "CreateMeshes":
            for row in fake.details.values():
                d = row["details"]
                points = d["polygonCoordinates"][:-1]
                if transform == "reverse":
                    points.reverse()
                elif transform == "shift":
                    points = points[1:] + points[:1]
                elif transform == "wrong-z":
                    points[1]["z"] += 0.1
                elif transform == "hole":
                    d["holes"] = [{"polygonCoordinates": points[:3]}]
                d["polygonCoordinates"] = points + [deepcopy(points[0])]
        return httpx.Response(200, json=response)

    async with ArchicadClient(transport=httpx.MockTransport(handler)) as c:
        result = await apply(c, [INPUT])
    assert result["items"][0]["status"] == (
        "verified" if transform in ("reverse", "shift") else "verification_failed"
    )


@pytest.mark.parametrize("edit", [False, True])
async def test_apply_requires_port_and_lost_answer_consumes_token(edit):
    fake = existing(lose_modify_response=True) if edit else model(lose_mesh_response=True)
    entries = [{"guid": GUID, "level": 0.5}] if edit else [INPUT]
    tool = meshes.modify_meshes if edit else meshes.create_meshes
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await tool(c, entries, 19723)
        with pytest.raises(ValueError, match="explicit port"):
            await tool(c, entries, None, False, preview["confirmation_token"])
        result = await tool(c, entries, 19723, False, preview["confirmation_token"])
        with pytest.raises(ValueError, match="consumed"):
            await tool(c, entries, 19723, False, preview["confirmation_token"])
    assert result["items"][0]["status"] == "unknown"
    assert fake.tapir_calls.count("ModifyMeshes" if edit else "CreateMeshes") == 1


async def test_modify_absolute_level_and_display_preserves_polygon_on_upper_story():
    fake = existing()
    fake.details[GUID]["floorIndex"] = 1
    before = deepcopy(fake.details[GUID]["details"]["polygonCoordinates"])
    change = {
        "guid": GUID,
        "level": 10,
        "skirt_type": "WithSkirt",
        "skirt_depth": 2,
        "ridges": "AllSmooth",
        "show_lines": False,
    }
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [change], edit=True)
    assert result["status"] == "verified"
    item = result["items"][0]
    assert item["mesh_edit_receipt_id"] and item["after"]["floorIndex"] == 1
    assert item["after"]["details"]["polygonCoordinates"] == before
    sent = next(r for r in fake.tapir_requests if r["command"] == "ModifyMeshes")
    assert sent["parameters"] == {
        "meshesData": [
            {
                "elementId": {"guid": GUID},
                "meshData": {
                    "level": 7,
                    "skirtType": "WithSkirt",
                    "skirtLevel": 2,
                    "ridges": "AllSmooth",
                    "showLines": False,
                },
            }
        ]
    }
    assert "polygonCoordinates" not in sent["parameters"]["meshesData"][0]["meshData"]


@pytest.mark.parametrize("reason", ["missing", "wrong-type", "locked", "hotlink"])
async def test_modify_unsafe_targets_refused(reason):
    fake = existing()
    if reason == "missing":
        fake.elements.pop(GUID)
        fake.details.pop(GUID)
    elif reason == "wrong-type":
        fake.elements[GUID] = "Wall"
        fake.details[GUID]["type"] = "Wall"
    elif reason == "locked":
        fake.locked_elements.add(GUID)
    else:
        fake.details[GUID]["hotlinkId"] = {"guid": OTHER}
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await meshes.modify_meshes(c, [{"guid": GUID, "level": 1}], 19723)
    assert "ModifyMeshes" not in fake.tapir_calls


@pytest.mark.parametrize(
    "entries",
    [
        [],
        [{"guid": GUID}],
        [{"guid": GUID, "level": 1}] * 2,
        [{"guid": GUID, "level": 1}] * 21,
        [{"guid": GUID, "floor_index": 1}],
        [{"guid": GUID, "outline": OUTLINE}],
        [{"guid": GUID, "skirt_depth": -1}],
    ],
)
async def test_modify_invalid_or_geometry_replacement_refused_before_network(entries):
    fake = existing()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await meshes.modify_meshes(c, entries)
    assert not fake.calls


async def test_modify_partial_failure_and_ignored_edit():
    fake = existing(modify_errors={1: MESHES_FIXTURE["modify_error"]})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(
            c, [{"guid": GUID, "level": 1}, {"guid": OTHER, "level": 1}], edit=True
        )
    assert [i["status"] for i in result["items"]] == ["verified", "failed"]
    fake = existing(modify_ignored=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [{"guid": GUID, "level": 1}], edit=True)
    assert result["items"][0]["status"] == "verification_failed"


async def test_modify_snapshot_and_prepared_receipt_guards(monkeypatch):
    fake = existing()
    entries = [{"guid": GUID, "level": 1}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await meshes.modify_meshes(c, entries, 19723)
        fake.details[GUID]["details"]["level"] = 0.5
        with pytest.raises(ValueError, match="changed"):
            await meshes.modify_meshes(c, entries, 19723, False, preview["confirmation_token"])
        preview = await meshes.modify_meshes(c, entries, 19723)

        def denied(*args):
            raise OSError("No receipt")

        monkeypatch.setattr(write, "_journal", denied)
        with pytest.raises(OSError, match="No receipt"):
            await meshes.modify_meshes(c, entries, 19723, False, preview["confirmation_token"])
    assert "ModifyMeshes" not in fake.tapir_calls


@pytest.mark.parametrize("field", ["holes", "polygonArcs", "sublines"])
async def test_modify_complex_meshes_refused_before_write(field):
    fake = existing()
    fake.details[GUID]["details"][field] = [{"synthetic": True}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="simple meshes"):
            await meshes.modify_meshes(c, [{"guid": GUID, "level": 1}], 19723)
    assert "ModifyMeshes" not in fake.tapir_calls


@pytest.mark.parametrize("edit", [False, True])
async def test_shared_timeout_used_for_mesh_write_and_readback(edit, monkeypatch):
    fake = existing() if edit else model()
    seen = []
    command = "ModifyMeshes" if edit else "CreateMeshes"

    class TimedClient(ArchicadClient):
        async def tapir(self, port, name, parameters=None, *, timeout=None):
            if timeout is not None:
                seen.append((name, timeout))
            return await super().tapir(port, name, parameters, timeout=timeout)

    monkeypatch.setenv("ARCHICAD_MCP_WRITE_TIMEOUT", "45")
    async with TimedClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [{"guid": GUID, "level": 1}] if edit else [INPUT], edit=edit)
    assert result["status"] == "verified" and result["write_timeout_seconds"] == 45
    assert (command, 45) in seen and ("GetDetailsOfElements", 45) in seen
