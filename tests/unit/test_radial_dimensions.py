"""Offline radial protocol contracts; live edge association remains unvalidated."""

from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import radial_dimensions as radial
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
SLAB = "11111111-1111-1111-1111-111111111111"
DIM = "22222222-2222-2222-2222-222222222222"
REQUEST = {
    "slab_guid": SLAB,
    "floor_index": 0,
    "arc_begin_index": 2,
    "favorite": "COTA RAIO - FORRO",
    "end_point": {"x": 2.0, "y": 2.0},
}


@pytest.fixture
def protocol(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))
    row = {
        "guid": DIM,
        "type": "RadialDimension",
        "floorIndex": 0,
        "radius": 1.0,
        "endPoint": REQUEST["end_point"],
        "style": {"linePen": 18},
        "existingGuids": [],
        "reference": {"elementGuid": SLAB, "nodeId": 6, "line": True},
    }
    plan = {
        "context": {"sessionId": "session", "projectEpoch": "epoch", "modificationStamp": "1"},
        "items": [row],
    }
    state = {"calls": [], "plan": plan, "mode": "ok"}

    async def addon(client, port, name, params=None, timeout=None):
        state["calls"].append(name)
        if name == "PlanRadialDimensions":
            return deepcopy(plan)
        if name == "CreateRadialDimensions":
            assert params["expectedPlan"] == plan
            if state["mode"] == "unknown":
                raise ArchicadError("Unknown native outcome")
            if row["existingGuids"]:
                return {"dimensions": [{"status": "existing", "existingGuids": [DIM]}]}
            return {"dimensions": [{"guid": DIM, "status": "created"}]}
        assert name == "GetRadialDimensions"
        actual = deepcopy(row)
        if state["mode"] == "detached":
            actual["reference"]["nodeId"] = 0
        return {"dimensions": [actual]}

    monkeypatch.setattr(radial.grids, "_addon", addon)
    return state


def client():
    return ArchicadClient(transport=fake_transport(FakeArchicad(19723)))


@pytest.mark.parametrize(
    "mode,status", [("ok", "verified"), ("detached", "verification_failed"), ("unknown", "unknown")]
)
async def test_radial_single_use_read_back(protocol, mode, status):
    async with client() as c:
        preview = await radial.create_radial_dimensions(c, [REQUEST], 19723)
        assert protocol["calls"] == ["PlanRadialDimensions"]
        protocol["mode"] = mode
        result = await radial.create_radial_dimensions(
            c, [REQUEST], 19723, False, preview["confirmation_token"]
        )
        assert result["items"][0]["status"] == status
        with pytest.raises(ValueError, match="consumed"):
            await radial.create_radial_dimensions(
                c, [REQUEST], 19723, False, preview["confirmation_token"]
            )
    assert protocol["calls"].count("CreateRadialDimensions") == 1


async def test_unresolved_edge_never_ready(protocol):
    protocol["plan"]["items"][0]["reference"]["nodeId"] = 0
    async with client() as c:
        with pytest.raises(ValueError, match="edge ID"):
            await radial.create_radial_dimensions(c, [REQUEST], 19723)


async def test_existing_radius_not_duplicated(protocol):
    protocol["plan"]["items"][0]["existingGuids"] = [DIM]
    async with client() as c:
        preview = await radial.create_radial_dimensions(c, [REQUEST], 19723)
        result = await radial.create_radial_dimensions(
            c, [REQUEST], 19723, False, preview["confirmation_token"]
        )
    assert result["items"][0]["element_guid"] == DIM


async def test_changed_context_blocks_radius(protocol):
    async with client() as c:
        preview = await radial.create_radial_dimensions(c, [REQUEST], 19723)
        protocol["plan"]["context"]["modificationStamp"] = "2"
        with pytest.raises(ValueError, match="changed"):
            await radial.create_radial_dimensions(
                c, [REQUEST], 19723, False, preview["confirmation_token"]
            )
    assert "CreateRadialDimensions" not in protocol["calls"]
