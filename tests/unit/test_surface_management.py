"""Source-derived official move shape, not a live Archicad capture."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from archicad_mcp_aberto.connection import ArchicadError
from archicad_mcp_aberto.tools import surface_management as sm

pytestmark = pytest.mark.anyio
SURFACE = "10000000-0000-4000-8000-000000000001"
FOLDER = "20000000-0000-4000-8000-000000000001"
CONTEXT = {
    "sessionId": "session",
    "projectEpoch": "epoch",
    "projectPath": "Working.pln",
    "modificationStamp": "1",
}
BEFORE = {
    "attributeId": {"guid": SURFACE},
    "index": 7,
    "name": "Stone",
    "texture": {"name": "original.png", "xSize": 2},
    "transparency": 0,
}


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))
    state = {"after": deepcopy(BEFORE), "context": deepcopy(CONTEXT)}

    async def planner(client, operation, requests, target_folder, port):
        return {
            "operation": operation,
            "target": {"port": 19723, "project": deepcopy(CONTEXT)},
            "folders": {},
            "file": {"size": 1},
            "items": [
                {
                    "index": 0,
                    "guid": SURFACE,
                    "status": "ready",
                    "before": deepcopy(BEFORE),
                    **(
                        {"new_name": "Rock"}
                        if operation == "rename"
                        else {"target_folder_guid": FOLDER}
                    ),
                }
            ],
        }

    monkeypatch.setattr(sm, "plan", planner)
    monkeypatch.setattr(
        sm.project_save, "_context", AsyncMock(side_effect=lambda *a: deepcopy(state["context"]))
    )
    monkeypatch.setattr(
        sm.model_tasks,
        "_settled_context",
        AsyncMock(side_effect=lambda *a: deepcopy(state["context"])),
    )
    backup = AsyncMock(
        side_effect=[{"confirmation_token": "backup"}, {"status": "verified", "task_token": "task"}]
    )
    save = AsyncMock(side_effect=[{"confirmation_token": "save"}, {"status": "verified"}])
    monkeypatch.setattr(sm.model_tasks, "begin_model_task", backup)
    monkeypatch.setattr(sm.model_tasks, "finish_model_task", save)
    monkeypatch.setattr(
        sm, "details", AsyncMock(side_effect=lambda *a: {SURFACE: deepcopy(state["after"])})
    )
    monkeypatch.setattr(sm, "folders", AsyncMock(return_value={FOLDER: {"attributes": [SURFACE]}}))

    class Client:
        session_id = uuid4()

        async def own_addon(self, port, name, parameters, **kwargs):
            state["after"]["name"] = parameters["renames"][0]["newName"]
            return {"results": [{"guid": SURFACE, "success": True}]}

        async def command(self, port, name, parameters, **kwargs):
            state["move"] = (name, parameters)
            return {}

    return Client(), state, backup, save


async def apply(client, operation="rename"):
    arguments = (client, operation, [{"guid": SURFACE, "new_name": "Rock"}])
    preview = await sm.manage_surfaces(*arguments, target_folder_guid=FOLDER, port=19723)
    result = await sm.manage_surfaces(
        *arguments,
        target_folder_guid=FOLDER,
        port=19723,
        dry_run=False,
        confirmation_token=preview["confirmation_token"],
    )
    return preview, result


async def test_rename_preserves_guid_texture_and_saves(setup):
    client, state, backup, save = setup
    _, result = await apply(client)
    assert result["status"] == "verified"
    assert result["items"][0]["after"]["attributeId"]["guid"] == SURFACE
    assert result["items"][0]["after"]["texture"] == BEFORE["texture"]
    assert backup.await_count == save.await_count == 2


async def test_move_uses_official_guid_wrappers_and_verifies_folder(setup):
    client, state, _, _ = setup
    _, result = await apply(client, "move")
    assert result["status"] == "verified"
    assert state["move"] == (
        "MoveAttributesAndFolders",
        {
            "attributeFolderIds": [],
            "attributeIds": [{"attributeId": {"guid": SURFACE}}],
            "targetFolderId": {"guid": FOLDER},
        },
    )


async def test_changed_texture_is_not_saved(setup):
    client, state, _, save = setup
    state["after"]["texture"]["name"] = "wrong.png"
    _, result = await apply(client)
    assert result["items"][0]["status"] == "verification_failed"
    save.assert_not_awaited()


async def test_unknown_write_is_not_retried_or_saved(setup):
    client, _, _, save = setup
    client.own_addon = AsyncMock(side_effect=ArchicadError("timeout"))
    _, result = await apply(client)
    assert result["items"][0]["status"] == "unknown"
    client.own_addon.assert_awaited_once()
    save.assert_not_awaited()


async def test_consumed_token_cannot_be_replayed(setup):
    client, _, _, _ = setup
    preview, _ = await apply(client)
    with pytest.raises(ValueError, match="consumed"):
        await sm.manage_surfaces(
            client,
            "rename",
            [{"guid": SURFACE}],
            port=19723,
            dry_run=False,
            confirmation_token=preview["confirmation_token"],
        )


async def test_changed_project_blocks_dispatch(setup):
    client, state, _, save = setup
    state["context"]["sessionId"] = "other"
    client.own_addon = AsyncMock()
    _, result = await apply(client)
    client.own_addon.assert_not_awaited()
    save.assert_not_awaited()
    assert result["status"] == "needs_review"


async def test_wrong_folder_readback_blocks_save(setup, monkeypatch):
    client, _, _, save = setup
    monkeypatch.setattr(sm, "folders", AsyncMock(return_value={FOLDER: {"attributes": []}}))
    _, result = await apply(client, "move")
    assert result["items"][0]["status"] == "verification_failed"
    save.assert_not_awaited()


def test_reference_scan_includes_face_override_and_nested_profile_surface():
    data = {
        "topSurface": 7,
        "buildingMaterial": 7,
        "profile": {"edge": {"attributeId": {"guid": SURFACE}}},
    }
    found = sm.references(data, {SURFACE: BEFORE}, {7: SURFACE})
    assert len(found) == 2
    assert all("buildingMaterial" not in path for _, path in found)


def test_folder_guid_and_membership_preserved():
    tree = sm.folder_tree(
        {
            "attributeFolderId": {"guid": FOLDER},
            "name": "Folder",
            "attributes": [{"attributeId": {"guid": SURFACE}}],
        }
    )
    assert tree[FOLDER]["attributes"] == [SURFACE]


async def test_no_use_found_never_authorizes_deletion(monkeypatch):
    audit = {
        "items": [{"guid": SURFACE, "status": "no_use_found", "proven_unused": False}],
        "limitations": ["incomplete SDK coverage"],
    }
    monkeypatch.setattr(sm, "audit_surface_usage", AsyncMock(return_value=audit))
    client = SimpleNamespace(command=AsyncMock(), own_addon=AsyncMock())
    result = await sm.delete_unused_surfaces(client, [SURFACE], 19723)
    assert result["deleted"] == 0
    assert result["status"] == "blocked_unproven_nonuse"
    client.command.assert_not_awaited()
    client.own_addon.assert_not_awaited()


def test_official_texture_name_is_part_of_configuration():
    row = {
        **BEFORE,
        "official": {
            "name": "Stone",
            "texture": {"name": "wood.jpg"},
            "renderSettings": {"roughness": 0.5},
        },
    }
    renamed = deepcopy(row)
    renamed["name"] = renamed["official"]["name"] = "Rock"
    assert sm.configuration(row) == sm.configuration(renamed)
    renamed["official"]["texture"]["name"] = "other.jpg"
    assert sm.configuration(row) != sm.configuration(renamed)


def test_hierarchy_ids_and_partial_errors_remain_visible():
    data = {
        "subelements": [
            {"cWallPanels": [{"elementId": {"guid": SURFACE}}]},
            {"error": {"message": "unsupported"}},
        ]
    }
    assert sm.element_references(data) == {SURFACE}
    assert sm.collect_errors(data) == [{"message": "unsupported"}]


async def test_preview_does_not_checkpoint_or_write(setup):
    client, _, backup, save = setup
    client.own_addon = AsyncMock()
    await sm.manage_surfaces(client, "rename", [{"guid": SURFACE}], port=19723)
    client.own_addon.assert_not_awaited()
    backup.assert_not_awaited()
    save.assert_not_awaited()


async def test_apply_requires_explicit_port(setup):
    client, _, backup, _ = setup
    preview = await sm.manage_surfaces(client, "rename", [{"guid": SURFACE}], port=19723)
    with pytest.raises(ValueError, match="Explicit port"):
        await sm.manage_surfaces(
            client,
            "rename",
            [{"guid": SURFACE}],
            dry_run=False,
            confirmation_token=preview["confirmation_token"],
        )
    backup.assert_not_awaited()


@pytest.mark.parametrize(
    "name", ["manage_surfaces", "audit_surface_usage", "delete_unused_surfaces"]
)
@pytest.mark.parametrize("explicit_none", [False, True])
@pytest.mark.parametrize("second_state", ["ready", "busy", "no_tapir"])
async def test_surface_tools_refuse_ambiguous_target(name, explicit_none, second_state):
    from archicad_mcp_aberto.connection import AmbiguousTarget
    from tests.unit.test_ambiguous_target import client, instances

    first, second = instances(second_state)
    arguments = {}
    if name == "manage_surfaces":
        arguments = {"operation": "rename", "requests": [{"guid": SURFACE, "new_name": "Rock"}]}
    elif name == "delete_unused_surfaces":
        arguments = {"surface_guids": [SURFACE]}
    if explicit_none:
        arguments["port"] = None
    async with client(first, second) as connection:
        with pytest.raises(AmbiguousTarget):
            await getattr(sm, name)(connection, **arguments)
    assert first.calls == second.calls == ["API.GetProductInfo"]
    assert first.tapir_calls == second.tapir_calls == []
