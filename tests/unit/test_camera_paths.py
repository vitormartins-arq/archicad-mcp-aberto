"""Offline task orchestration; native view/camera APIs simulated, never live."""

import json
from copy import deepcopy
from uuid import uuid4

import pytest

from archicad_mcp_aberto.connection import ArchicadError
from archicad_mcp_aberto.tools import camera_paths as cameras
from tests.unit.test_model_tasks import client
from tests.unit.test_model_tasks import native_task as native_task

pytestmark = pytest.mark.anyio
IDS = [f"10000000-0000-4000-8000-{n:012d}" for n in range(1, 5)]


@pytest.fixture
def native_cameras(native_task, monkeypatch):
    state = native_task
    rows = [
        dict(
            sourceViewGuid=guid,
            name=f"View {index}",
            isPerspective=index != 1,
            projection={"x": index, "targetX": index + 2, "viewConeNative": 60.0},
            representationJSON=json.dumps({"layers": "other" if index == 3 else "main"}),
        )
        for index, guid in enumerate(IDS)
    ]
    inventory = dict(paths=[], cameras=[], cameraPathDisplayMode=4)
    state.update(
        rows=rows,
        inventory=inventory,
        creates=0,
        prepare_restored=True,
        camera_timeout=False,
        change_source_on_checkpoint=False,
    )
    tokens = {}
    base_addon = state["addon"]

    async def tree(*args, **kwargs):
        return [
            dict(
                guid=r["sourceViewGuid"],
                name=r["name"],
                type="PerspectiveItem" if r["isPerspective"] else "AxonometryItem",
            )
            for r in rows
        ]

    async def addon(c, port, name, parameters=None, timeout=None):
        if name in {"GetProjectSaveContext", "SaveCurrentProjectPLN"}:
            result = await base_addon(c, port, name, parameters, timeout)
            if name == "SaveCurrentProjectPLN" and state["change_source_on_checkpoint"]:
                rows[0]["projection"]["x"] += 1
            return result
        state["calls"].append(name)
        if name == "GetCameraPaths":
            return deepcopy(inventory)
        if name == "PrepareCameraPath":
            selected = [
                deepcopy(next(r for r in rows if r["sourceViewGuid"] == guid))
                for guid in parameters["viewGuids"]
            ]
            token = str(uuid4())
            tokens[token] = {"rows": selected, "name": parameters["pathName"]}
            return dict(
                views=selected,
                nativeToken=token,
                context=deepcopy(state["context"]),
                stateRestored=state["prepare_restored"],
                inventory=deepcopy(inventory),
            )
        assert name == "ApplyCameraPath"
        assert list(state["receipts"].glob("*.path-*-prepared.json"))
        assert any(
            p.read_bytes() == b"UNSAVED_BEFORE_TASK"
            for p in (state["source"].parent / "Anteriores").glob("*.pln")
        )
        plan = tokens.pop(parameters["nativeToken"])
        path = next((p for p in inventory["paths"] if p["name"] == plan["name"]), None)
        if path is None:
            path = dict(guid=str(uuid4()), name=plan["name"])
            inventory["paths"].append(path)
        created, reused = [], 0
        for row in plan["rows"]:
            existing = next(
                (
                    r
                    for r in inventory["cameras"]
                    if r["pathGuid"] == path["guid"]
                    and r["sourceViewGuid"] == row["sourceViewGuid"]
                ),
                None,
            )
            if existing:
                reused += 1
                continue
            camera = dict(
                guid=str(uuid4()),
                pathGuid=path["guid"],
                sourceViewGuid=row["sourceViewGuid"],
                projection=row["projection"],
            )
            inventory["cameras"].append(camera)
            created.append(camera)
            state["creates"] += 1
        inventory["cameraPathDisplayMode"] = 1
        state["context"]["modificationStamp"] = str(int(state["context"]["modificationStamp"]) + 1)
        state["pending"] = b"MODEL_WITH_PHYSICAL_CAMERAS"
        if state["camera_timeout"]:
            raise ArchicadError("Timed out after native creation")
        return dict(
            pathGuid=path["guid"],
            pathName=path["name"],
            created=created,
            reusedCount=reused,
            verifiedCount=len(plan["rows"]),
            hiddenInPlan=True,
            inventory=deepcopy(inventory),
        )

    monkeypatch.setattr(cameras.navigator, "_view_tree", tree)
    monkeypatch.setattr(cameras.grids, "_addon", addon)
    return state


async def apply(c):
    preview = await cameras.create_camera_paths_from_views(c, port=19723)
    return preview, await cameras.create_camera_paths_from_views(
        c, port=19723, dry_run=False, confirmation_token=preview["confirmation_token"]
    )


async def test_physical_camera_groups_backup_before_creation_save_same_path(native_cameras):
    state = native_cameras
    async with client() as c:
        preview, result = await apply(c)
    assert len(preview["groups"]) == 2 and len(preview["skipped"]) == 1
    assert preview["groups"][0]["path_name"] == "BIMx - Apresentação"
    assert [v["sourceViewGuid"] for v in preview["groups"][0]["views"]] == [IDS[0], IDS[2]]
    assert result["status"] == "verified" and state["creates"] == 3
    assert state["source"].name == "Working.pln" and state["saves"] == 2
    assert state["source"].read_bytes() == b"MODEL_WITH_PHYSICAL_CAMERAS"
    assert all("inventory" not in p["result"] for p in result["paths"])


async def test_preview_does_not_save_or_create(native_cameras):
    async with client() as c:
        await cameras.create_camera_paths_from_views(c, port=19723)
    assert native_cameras["saves"] == native_cameras["creates"] == 0
    assert not (native_cameras["source"].parent / "Anteriores").exists()


async def test_requested_sources_are_sorted_in_navigator_order(native_cameras):
    async with client() as c:
        plan = await cameras.create_camera_paths_from_views(
            c, view_guids=[IDS[2], IDS[0]], port=19723
        )
    assert [v["sourceViewGuid"] for v in plan["groups"][0]["views"]] == [IDS[0], IDS[2]]


async def test_failed_state_restoration_blocks_preview(native_cameras):
    native_cameras["prepare_restored"] = False
    async with client() as c:
        with pytest.raises(ValueError, match="restoration"):
            await cameras.create_camera_paths_from_views(c, port=19723)
    assert native_cameras["saves"] == native_cameras["creates"] == 0


@pytest.mark.parametrize("change", ["project", "disk", "inventory"])
async def test_stale_preview_is_refused_before_backup(native_cameras, change):
    async with client() as c:
        plan = await cameras.create_camera_paths_from_views(c, port=19723)
        if change == "project":
            native_cameras["context"]["projectEpoch"] = "reopened"
        elif change == "disk":
            native_cameras["source"].write_bytes(b"CHANGED_EXTERNALLY")
        else:
            native_cameras["inventory"]["cameraPathDisplayMode"] = 1
        with pytest.raises(ValueError):
            await cameras.create_camera_paths_from_views(
                c, port=19723, dry_run=False, confirmation_token=plan["confirmation_token"]
            )
    assert native_cameras["saves"] == native_cameras["creates"] == 0


async def test_source_change_during_checkpoint_never_creates_cameras(native_cameras):
    native_cameras["change_source_on_checkpoint"] = True
    async with client() as c:
        _, result = await apply(c)
    assert result["status"] == "needs_review" and native_cameras["creates"] == 0
    assert native_cameras["saves"] == 1


async def test_native_timeout_never_retries_or_saves_unknown_result(native_cameras):
    native_cameras["camera_timeout"] = True
    async with client() as c:
        plan, result = await apply(c)
        assert result["status"] == "needs_review" and native_cameras["saves"] == 1
        with pytest.raises(ValueError, match="consumed"):
            await cameras.create_camera_paths_from_views(
                c, port=19723, dry_run=False, confirmation_token=plan["confirmation_token"]
            )
    assert native_cameras["creates"] == 2
