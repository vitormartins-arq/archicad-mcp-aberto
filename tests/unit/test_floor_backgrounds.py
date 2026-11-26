"""Offline guard tests; not evidence of Archicad rendering or Undo."""

from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import floor_backgrounds as floors
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
SLAB = "11111111-1111-1111-1111-111111111111"
SCOPE = "22222222-2222-2222-2222-222222222222"
VIEW = "33333333-3333-3333-3333-333333333333"


@pytest.fixture
def protocol(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))
    row = {
        "guid": SLAB,
        "surfaceGuid": VIEW,
        "surfaceColor": {"red": 0.2, "green": 0.3, "blue": 0.4},
        "preserved": {
            "fill": {"foregroundPen": 109, "use3DHatching": True},
            "orientation": {"origin": {"x": 7, "y": 8}, "matrix10": 0.5},
            "arcs": [{"begin": 2, "end": 3, "angle": 0.4}],
            "ringEnds": [5, 10],
        },
        "preservedVisual": {"foregroundOverridden": False},
    }
    plan = {
        "context": {
            "sessionId": "s",
            "projectEpoch": "e",
            "modificationStamp": 1,
            "isUntitled": True,
        },
        "slabs": [row],
        "baseCombinationName": "Base",
    }
    state = {
        "calls": [],
        "mode": "ok",
        "view": {"graphicOverrideCombination": "Base", "rotation": 0.3, "drawingScale": 50},
    }

    async def native(client, port, name, params=None, timeout=None):
        state["calls"].append(name)
        if name == "PlanFloorSurfaceBackgrounds":
            return deepcopy(plan)
        if name == "SetFloorSurfaceBackgrounds":
            assert params["expectedPlan"] == plan
            if state["mode"] == "timeout":
                raise ArchicadError("Unknown result", detail={"stage": "create_rgb_rule"})
            return {"verified": True, "slabCount": 1, "combinationName": "Scoped"}
        assert name == "GetFloorSurfaceBackgroundState"
        actual = deepcopy(row)
        actual["effectiveBackgroundRGB"] = deepcopy(row["surfaceColor"])
        if state["mode"] == "orientation":
            actual["preserved"]["orientation"]["matrix10"] = 0.6
        if state["mode"] == "rgb":
            actual["effectiveBackgroundRGB"]["red"] = 0.9
        return {"slabs": [actual]}

    async def settings(client, port, guids, timeout=None):
        return [deepcopy(state["view"])]

    monkeypatch.setattr(floors.grids, "_addon", native)
    monkeypatch.setattr(floors.views, "_settings", settings)
    return state, plan


def client():
    return ArchicadClient(transport=fake_transport(FakeArchicad(19723)))


async def test_preview_reads_only(protocol):
    state, _ = protocol
    async with client() as c:
        preview = await floors.set_floor_surface_backgrounds(c, [SLAB], SCOPE, 19723)
    assert preview["dry_run"]
    assert state["calls"] == ["PlanFloorSurfaceBackgrounds"]


@pytest.mark.parametrize(
    "mode,status",
    [("ok", "verified"), ("rgb", "unknown"), ("orientation", "unknown"), ("timeout", "unknown")],
)
async def test_exact_readback_and_no_retry(protocol, mode, status):
    state, _ = protocol
    async with client() as c:
        preview = await floors.set_floor_surface_backgrounds(c, [SLAB], SCOPE, 19723)
        state["mode"] = mode
        result = await floors.set_floor_surface_backgrounds(
            c, [SLAB], SCOPE, 19723, dry_run=False, confirmation_token=preview["confirmation_token"]
        )
        assert result["items"][0]["status"] == status
        with pytest.raises(ValueError, match="consumed"):
            await floors.set_floor_surface_backgrounds(
                c,
                [SLAB],
                SCOPE,
                19723,
                dry_run=False,
                confirmation_token=preview["confirmation_token"],
            )
    assert state["calls"].count("SetFloorSurfaceBackgrounds") == 1


async def test_changed_geometry_rejects_stale_preview(protocol):
    state, plan = protocol
    async with client() as c:
        preview = await floors.set_floor_surface_backgrounds(c, [SLAB], SCOPE, 19723)
        plan["slabs"][0]["preserved"]["ringEnds"] = [6, 11]
        with pytest.raises(ValueError, match="changed"):
            await floors.set_floor_surface_backgrounds(
                c,
                [SLAB],
                SCOPE,
                19723,
                dry_run=False,
                confirmation_token=preview["confirmation_token"],
            )
    assert "SetFloorSurfaceBackgrounds" not in state["calls"]


async def test_saved_project_requires_checkpoint(protocol):
    state, plan = protocol
    plan["context"]["isUntitled"] = False
    async with client() as c:
        with pytest.raises(ValueError, match="checkpoint"):
            await floors.set_floor_surface_backgrounds(c, [SLAB], SCOPE, 19723)
    assert "SetFloorSurfaceBackgrounds" not in state["calls"]


async def test_view_must_match_current_representation(protocol):
    state, _ = protocol
    state["view"]["graphicOverrideCombination"] = "Other"
    async with client() as c:
        with pytest.raises(ValueError, match="target saved view"):
            await floors.set_floor_surface_backgrounds(c, [SLAB], SCOPE, 19723, VIEW)


async def test_duplicate_targets_rejected(protocol):
    async with client() as c:
        with pytest.raises(ValueError, match="Duplicate"):
            await floors.set_floor_surface_backgrounds(c, [SLAB, SLAB], SCOPE, 19723)


async def test_saved_view_changes_only_combination(protocol, monkeypatch):
    state, _ = protocol
    sent = []
    async with client() as c:
        original = c.tapir

        async def tapir(port, name, params=None, timeout=None):
            if name != "SetViewSettings":
                return await original(port, name, params, timeout=timeout)
            sent.append(params)
            settings = params["navigatorItemIdsWithViewSettings"][0]["viewSettings"]
            assert settings == {"graphicOverrideCombination": "Scoped"}
            state["view"].update(settings)
            return {"executionResults": [{"success": True}]}

        monkeypatch.setattr(c, "tapir", tapir)
        preview = await floors.set_floor_surface_backgrounds(c, [SLAB], SCOPE, 19723, VIEW)
        result = await floors.set_floor_surface_backgrounds(
            c,
            [SLAB],
            SCOPE,
            19723,
            VIEW,
            dry_run=False,
            confirmation_token=preview["confirmation_token"],
        )
    assert result["status"] == "verified"
    assert len(sent) == 1
    assert state["view"] == {
        "graphicOverrideCombination": "Scoped",
        "rotation": 0.3,
        "drawingScale": 50,
    }
