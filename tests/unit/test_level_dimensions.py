"""Offline protocol mocks: new native commands still require coordinated live acceptance."""

from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import ArchicadClient, ArchicadError
from archicad_mcp_aberto.tools import level_dimensions as levels
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
SLAB = "11111111-1111-1111-1111-111111111111"
DIM = "22222222-2222-2222-2222-222222222222"
REQUEST = {
    "point": {"x": 1.0, "y": 2.0},
    "floor_index": 0,
    "slab_guid": SLAB,
    "favorite": "COTA DE NÍVEL - PISO",
}


@pytest.fixture
def native(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path / "receipts"))
    row = {
        "type": "LevelDimension",
        "floorIndex": 0,
        "parentGuid": SLAB,
        "parentType": 5,
        "static": False,
        "point": {"x": 1.0, "y": 2.0},
        "measuredLevel": 0.02,
        "topElevationProject": 0.02,
        "bottomElevationProject": 0.0,
        "layerIndex": 4,
        "pen": 18,
        "symbol": 1,
        "markerSize": 3.0,
        "angle": 0.0,
        "needPlus": True,
        "origin": 0,
        "hideWithBaseElement": False,
        "note1": {"font": 1, "size": 2.0, "content": "<native-top-autotext>"},
        "note2": {"font": 1, "size": 2.0, "content": "<native-bottom-autotext>"},
        "existingGuids": [],
    }
    plan = {
        "context": {"sessionId": "session", "projectEpoch": "epoch", "modificationStamp": "1"},
        "precision": {"unit": 0, "decimals": 2},
        "items": [row],
    }
    control = {"calls": [], "mode": "ok", "plan": plan}

    async def addon(client, port, name, params=None, timeout=None):
        assert port == 19723
        control["calls"].append((name, deepcopy(params)))
        if name == "PlanLevelDimensions":
            return deepcopy(plan)
        if name == "CreateLevelDimensions":
            assert params["expectedPlan"] == plan
            assert params["dimensions"][0]["favorite"] == REQUEST["favorite"]
            if control["mode"] == "timeout":
                raise ArchicadError("Unknown native outcome")
            if control["mode"] == "bad_count":
                return {"dimensions": []}
            if row["existingGuids"]:
                return {
                    "dimensions": [{"status": "existing", "existingGuids": row["existingGuids"]}]
                }
            return {"dimensions": [{"status": "created", "guid": DIM}]}
        assert name == "GetLevelDimensions"
        actual = deepcopy(row)
        actual.update(guid=DIM, drawingError=0, drawnTexts=[{"text": "NA +0.02 NO ±0.00"}])
        if control["mode"] == "static":
            actual["static"] = True
        if control["mode"] == "wrong_parent":
            actual["parentGuid"] = DIM
        if control["mode"] == "wrong_value":
            actual["measuredLevel"] = 0
        if control["mode"] == "wrong_style":
            actual["note1"]["size"] = 9
        if control["mode"] == "no_drawing":
            actual["drawnTexts"] = []
        if control["mode"] == "wrong_type":
            actual["type"] = "Text"
        return {"dimensions": [actual]}

    monkeypatch.setattr(levels.grids, "_addon", addon)
    return control


def client():
    return ArchicadClient(transport=fake_transport(FakeArchicad(19723)))


async def test_preview_preserves_exact_favorite_and_no_writes(native):
    async with client() as c:
        p = await levels.create_level_dimensions(c, [REQUEST], 19723)
    assert p["dry_run"] and p["items"][0]["expected"]["topElevationProject"] == 0.02
    assert p["items"][0]["expected"]["bottomElevationProject"] == 0
    assert [n for n, p in native["calls"]] == ["PlanLevelDimensions"]
    assert p["items"][0]["parameters"]["reference"] == "favorite"


async def test_create_readback_and_token_replay(native):
    async with client() as c:
        p = await levels.create_level_dimensions(c, [REQUEST], 19723)
        r = await levels.create_level_dimensions(
            c, [REQUEST], 19723, False, p["confirmation_token"]
        )
        with pytest.raises(ValueError, match="consumed"):
            await levels.create_level_dimensions(
                c, [REQUEST], 19723, False, p["confirmation_token"]
            )
    assert r["status"] == "verified"
    assert r["items"][0]["readback"]["type"] == "LevelDimension"
    assert native["calls"][-1][1] == {"guids": [DIM], "includeDrawing": True}


@pytest.mark.parametrize(
    "mode,field",
    [
        ("static", "static"),
        ("wrong_parent", "parentGuid"),
        ("wrong_value", "measuredLevel"),
        ("wrong_style", "note1"),
        ("no_drawing", "drawnTexts"),
        ("wrong_type", "type"),
    ],
)
async def test_bad_association_value_style_or_drawing_never_verified(native, mode, field):
    native["mode"] = mode
    async with client() as c:
        p = await levels.create_level_dimensions(c, [REQUEST], 19723)
        r = await levels.create_level_dimensions(
            c, [REQUEST], 19723, False, p["confirmation_token"]
        )
    assert r["status"] == "needs_review"
    assert field in r["items"][0]["mismatches"]


async def test_existing_cota_is_read_and_checked(native):
    native["plan"]["items"][0]["existingGuids"] = [DIM]
    async with client() as c:
        p = await levels.create_level_dimensions(c, [REQUEST], 19723)
        r = await levels.create_level_dimensions(
            c, [REQUEST], 19723, False, p["confirmation_token"]
        )
    assert p["items"][0]["duplicate_guids"] == [DIM]
    assert r["status"] == "verified"


@pytest.mark.parametrize("mode", ["timeout", "bad_count"])
async def test_unknown_write_never_retried(native, mode):
    native["mode"] = mode
    async with client() as c:
        p = await levels.create_level_dimensions(c, [REQUEST], 19723)
        r = await levels.create_level_dimensions(
            c, [REQUEST], 19723, False, p["confirmation_token"]
        )
    assert r["items"][0]["status"] == "unknown"
    assert sum(n == "CreateLevelDimensions" for n, p in native["calls"]) == 1


@pytest.mark.parametrize("change", ["stamp", "favorite", "precision", "duplicates", "host_top"])
async def test_native_snapshot_changes_refuse_apply(native, change):
    async with client() as c:
        p = await levels.create_level_dimensions(c, [REQUEST], 19723)
        if change == "stamp":
            native["plan"]["context"]["modificationStamp"] = "2"
        if change == "favorite":
            native["plan"]["items"][0]["note1"]["size"] = 4
        if change == "precision":
            native["plan"]["precision"]["decimals"] = 3
        if change == "duplicates":
            native["plan"]["items"][0]["existingGuids"] = [DIM]
        if change == "host_top":
            native["plan"]["items"][0]["topElevationProject"] = 0.03
        with pytest.raises(ValueError, match="changed"):
            await levels.create_level_dimensions(
                c, [REQUEST], 19723, False, p["confirmation_token"]
            )
    assert not any(n == "CreateLevelDimensions" for n, p in native["calls"])


async def test_explicit_top_bottom_project_datum_are_sent(native):
    request = {**REQUEST, "reference": "bottom", "datum": "project_zero"}
    async with client() as c:
        await levels.create_level_dimensions(c, [request], 19723)
    assert native["calls"][0][1]["dimensions"][0]["reference"] == "bottom"
    assert native["calls"][0][1]["dimensions"][0]["datum"] == "project_zero"


@pytest.mark.parametrize("count", [0, 21])
async def test_bounded_batch(native, count):
    async with client() as c:
        with pytest.raises(ValueError):
            await levels.create_level_dimensions(c, [REQUEST] * count, 19723)
    assert not native["calls"]


async def test_invalid_native_data_refused(native):
    native["plan"]["items"][0]["measuredLevel"] = float("nan")
    async with client() as c:
        with pytest.raises(ValueError, match="nonfinite"):
            await levels.create_level_dimensions(c, [REQUEST], 19723)
