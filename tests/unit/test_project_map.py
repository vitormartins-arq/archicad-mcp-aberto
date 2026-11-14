"""Project Map organization against a simulated companion add-on."""

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import grids, project_map
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio

FOLDER = "37653D28-97B7-4B24-B938-276DBC009703"
DETAILS = "2AFA9DD8-39B8-46F8-B83F-90632AB714E8"
DETAIL = "11111111-0000-0000-0000-000000000001"


def _preview(operations):
    rows = []
    for op in operations:
        if op["action"] == "rename":
            rows.append({"action": "rename", "status": "ok", "name": "Banheiro social"})
        elif op.get("parentGuid") == "BLOCK":
            rows.append(
                {"action": op["action"], "status": "blocked", "reason": "different categories"}
            )
        else:
            rows.append({"action": op["action"], "status": "manual", "to": "Detalhes / Banheiro"})
    return rows


@pytest.fixture
def addon(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path / "receipts"))
    calls = []

    async def fake(client, port, name, parameters=None, timeout=None):
        calls.append((name, parameters))
        if name == "GetProjectMapTree":
            return {
                "items": [
                    {"guid": DETAILS, "category": "details", "isCategory": True},
                    {"guid": FOLDER, "category": "sections", "type": "folder"},
                ]
            }
        preview = _preview(parameters["operations"])
        if not parameters.get("apply"):
            return {"preview": preview, "blocked": 0, "manual": 0, "applied": False}
        return {
            "preview": preview,
            "results": [{"action": "rename", "result": "done"}],
            "verification": [{"action": "rename", "ok": True}],
            "links": {"viewMapItemsLost": 0, "drawingsLost": 0},
            "applied": True,
            "refused": 0,
            "mismatches": 0,
        }

    monkeypatch.setattr(grids, "_addon", fake)
    return calls


def _client():
    return ArchicadClient(transport=fake_transport(FakeArchicad(19723)))


async def test_read_filters_by_category(addon):
    async with _client() as c:
        result = await project_map.get_project_map(c, "details", port=19723)
    assert [i["guid"] for i in result["items"]] == [DETAILS]


async def test_preview_then_apply_runs_renames_and_lists_manual_steps(addon):
    ops = [
        {"action": "rename", "guid": FOLDER, "name": "BANHEIRO SOCIAL"},
        {"action": "create_folder", "key": "b", "parent_guid": DETAILS, "name": "Banheiro"},
        {"action": "move", "guid": DETAIL, "parent_key": "b"},
    ]
    async with _client() as c:
        preview = await project_map.organize_project_map(c, ops, 19723)
        assert not any(p and p.get("apply") for _, p in addon)
        item = preview["items"][0]
        assert item["operations"][1] == {
            "action": "createFolder",
            "key": "b",
            "parentGuid": DETAILS,
            "name": "Banheiro",
        }
        assert len(item["manual_steps"]) == 2
        done = await project_map.organize_project_map(
            c, ops, 19723, False, preview["confirmation_token"]
        )
    assert done["items"][0]["status"] == "verified"
    assert addon[-1][1]["apply"] is True


async def test_blocked_plan_is_refused(addon):
    ops = [{"action": "move", "guid": DETAIL, "parent_guid": "BLOCK"}]
    async with _client() as c:
        with pytest.raises(ValueError, match="different categories"):
            await project_map.organize_project_map(c, ops, 19723)


async def test_unknown_action_is_rejected(addon):
    async with _client() as c:
        with pytest.raises(ValueError):
            await project_map.organize_project_map(c, [{"action": "delete", "guid": FOLDER}], 19723)
