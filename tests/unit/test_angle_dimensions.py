"""Offline angular protocol tests; not evidence of native associativity."""

from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import angle_dimensions as angles
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
PARENT = "11111111-1111-1111-1111-111111111111"
DIM = "22222222-2222-2222-2222-222222222222"
REQUEST = {
    "favorite": "COTA DE ÂNGULO PARALELA - FORRO",
    "floor_index": 0,
    "position": {"x": 1.0, "y": 1.0},
    "references": [{"element_guid": PARENT, "in_index": i, "neig_id": 1} for i in range(4)],
}


@pytest.fixture
def protocol(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))
    row = {
        "guid": DIM,
        "type": "AngleDimension",
        "floorIndex": 0,
        "angle": 1.0,
        "radius": 1.0,
        "position": REQUEST["position"],
        "origin": {"x": 0.0, "y": 0.0},
        "style": {"linePen": 18, "note": {"size": 2.0}},
        "existingGuids": [],
        "references": [{"elementGuid": PARENT, "inIndex": i} for i in range(4)],
    }
    plan = {
        "context": {"sessionId": "session", "projectEpoch": "epoch", "modificationStamp": "1"},
        "items": [row],
    }
    state = {"calls": [], "plan": plan, "mode": "ok"}

    async def native(client, port, name, params=None, timeout=None):
        state["calls"].append(name)
        if name == "PlanAngleDimensions":
            return deepcopy(plan)
        if name == "CreateAngleDimensions":
            assert params["expectedPlan"] == plan
            if state["mode"] == "unknown":
                raise ArchicadError("Unknown native outcome", detail={"stage": "create"})
            if row["existingGuids"]:
                return {"dimensions": [{"status": "existing", "existingGuids": [DIM]}]}
            return {"dimensions": [{"status": "created", "guid": DIM}]}
        assert name == "GetAngleDimensions"
        found = deepcopy(row)
        if state["mode"] == "detached":
            found["references"][0]["elementGuid"] = DIM
        return {"dimensions": [found]}

    monkeypatch.setattr(angles.grids, "_addon", native)
    return state


def client():
    return ArchicadClient(transport=fake_transport(FakeArchicad(19723)))


async def test_preview_and_exact_favorite(protocol):
    async with client() as c:
        result = await angles.create_angle_dimensions(c, [REQUEST], 19723)
    assert result["dry_run"]
    assert result["items"][0]["parameters"]["favorite"] == REQUEST["favorite"]
    assert protocol["calls"] == ["PlanAngleDimensions"]


@pytest.mark.parametrize(
    "mode,expected",
    [("ok", "verified"), ("detached", "verification_failed"), ("unknown", "unknown")],
)
async def test_apply_readback_and_unknown_not_retried(protocol, mode, expected):
    async with client() as c:
        preview = await angles.create_angle_dimensions(c, [REQUEST], 19723)
        protocol["mode"] = mode
        result = await angles.create_angle_dimensions(
            c, [REQUEST], 19723, False, preview["confirmation_token"]
        )
        assert result["items"][0]["status"] == expected
        with pytest.raises(ValueError, match="consumed"):
            await angles.create_angle_dimensions(
                c, [REQUEST], 19723, False, preview["confirmation_token"]
            )
    assert protocol["calls"].count("CreateAngleDimensions") == 1


async def test_stale_plan_blocks_apply(protocol):
    async with client() as c:
        preview = await angles.create_angle_dimensions(c, [REQUEST], 19723)
        protocol["plan"]["context"]["modificationStamp"] = "2"
        with pytest.raises(ValueError, match="changed"):
            await angles.create_angle_dimensions(
                c, [REQUEST], 19723, False, preview["confirmation_token"]
            )
    assert "CreateAngleDimensions" not in protocol["calls"]


async def test_existing_is_read_back(protocol):
    protocol["plan"]["items"][0]["existingGuids"] = [DIM]
    async with client() as c:
        preview = await angles.create_angle_dimensions(c, [REQUEST], 19723)
        result = await angles.create_angle_dimensions(
            c, [REQUEST], 19723, False, preview["confirmation_token"]
        )
    assert result["items"][0]["element_guid"] == DIM
    assert result["items"][0]["status"] == "verified"


async def test_no_static_reference_fallback(protocol):
    protocol["plan"]["items"][0]["references"][0]["elementGuid"] = DIM
    async with client() as c:
        with pytest.raises(ValueError, match="association"):
            await angles.create_angle_dimensions(c, [REQUEST], 19723)


@pytest.mark.parametrize("count", [0, 21])
async def test_batch_bound(protocol, count):
    async with client() as c:
        with pytest.raises(ValueError, match="1..20"):
            await angles.create_angle_dimensions(c, [REQUEST] * count, 19723)
