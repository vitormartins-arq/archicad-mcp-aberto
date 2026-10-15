"""New Navigator writes against the source-derived fake, never Archicad."""

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import navigator
from tests.unit.fake_archicad import FakeArchicad, _view_map_node, fake_transport

pytestmark = pytest.mark.anyio
ROOT = "77777777-7777-4777-8777-000000000001"
FOLDER = "77777777-7777-4777-8777-000000000002"
VIEW = "77777777-7777-4777-8777-000000000003"
SOURCE = "88888888-8888-4888-8888-000000000002"
PROJECT_ROOT = "88888888-8888-4888-8888-000000000001"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def entries(kind):
    if kind == "folders":
        return [
            {"parent_guid": ROOT, "name": "Documentação"},
            {"parent_guid": FOLDER, "name": "Detalhes"},
        ]
    return [
        {"parent_guid": FOLDER, "source_guid": SOURCE},
        {"parent_guid": ROOT, "source_guid": SOURCE},
    ]


def tool(kind):
    return navigator.create_view_map_folders if kind == "folders" else navigator.clone_to_view_map


@pytest.mark.parametrize("kind", ["folders", "clones"])
async def test_preview_apply_tree_receipts_and_token(kind):
    fake = FakeArchicad(19723)
    before_project = deepcopy(fake.navigator_trees["ProjectMap"])
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await tool(kind)(c, entries(kind))
        token = preview["confirmation_token"]
        assert not any(n.startswith(("Create", "Clone")) for n in fake.tapir_calls)
        result = await tool(kind)(c, entries(kind), 19723, False, token)
        with pytest.raises(ValueError, match="consumed"):
            await tool(kind)(c, entries(kind), 19723, False, token)
    assert result["status"] == "verified"
    assert len({i["navigator_guid"] for i in result["items"]}) == 2
    assert fake.navigator_trees["ProjectMap"] == before_project
    assert "No guaranteed Navigator Undo" in result["note"]
    saved = json.loads(Path(result["receipt_path"]).read_text())
    assert saved["counts"]["verified"] == 2
    assert not any(n.startswith(("Save", "Delete", "Move", "Publish")) for n in fake.tapir_calls)
    command = "CreateViewMapFolder" if kind == "folders" else "CloneProjectMapItemToViewMap"
    sent = [r["parameters"] for r in fake.tapir_requests if r["command"] == command]
    if kind == "folders":
        assert sent[0] == {"folderName": "Documentação", "parentNavigatorItemId": {"guid": ROOT}}
    else:
        assert sent[0] == {
            "viewsData": [
                {"navigatorItemId": {"guid": SOURCE}, "parentNavigatorItemId": {"guid": FOLDER}}
            ]
        }


@pytest.mark.parametrize("kind", ["folders", "clones"])
@pytest.mark.parametrize(
    "fault",
    [
        "empty",
        "too_many",
        "bad_guid",
        "null_guid",
        "missing_parent",
        "view_parent",
        "project_parent",
        "duplicate",
        "extra",
    ],
)
async def test_preflight_refusals(kind, fault):
    data = entries(kind)[:1]
    if fault == "empty":
        data = []
    elif fault == "too_many":
        data *= 21
    elif fault == "duplicate":
        data *= 2
    elif fault == "extra":
        data[0]["save"] = True
    else:
        data[0]["parent_guid"] = {
            "bad_guid": "bad",
            "null_guid": "00000000-0000-0000-0000-000000000000",
            "missing_parent": "11111111-1111-4111-8111-111111111111",
            "view_parent": VIEW,
            "project_parent": PROJECT_ROOT,
        }[fault]
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await tool(kind)(c, data)
    assert not any(n.startswith(("Create", "Clone")) for n in fake.tapir_calls)


@pytest.mark.parametrize("bad", ["", " ", " Folder "])
async def test_blank_folder_names(bad):
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as c:
        with pytest.raises(ValueError):
            await navigator.create_view_map_folders(c, [{"parent_guid": ROOT, "name": bad}])


@pytest.mark.parametrize(
    "bad", [ROOT, PROJECT_ROOT, FOLDER, "11111111-1111-4111-8111-111111111111"]
)
async def test_invalid_clone_sources(bad):
    async with ArchicadClient(transport=fake_transport(FakeArchicad(19723))) as c:
        with pytest.raises(ValueError, match="Source"):
            await navigator.clone_to_view_map(c, [{"parent_guid": FOLDER, "source_guid": bad}])


@pytest.mark.parametrize("kind", ["folders", "clones"])
async def test_port_stale_preview_and_existing_name(kind):
    fake = FakeArchicad(19723)
    data = entries(kind)[:1]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await tool(kind)(c, data, 19723)
        with pytest.raises(ValueError, match="explicit port"):
            await tool(kind)(c, data, None, False, preview["confirmation_token"])
        _view_map_node(fake.navigator_trees["PublicViewMap"], FOLDER)["name"] = "Changed"
        with pytest.raises(ValueError, match="changed"):
            await tool(kind)(c, data, 19723, False, preview["confirmation_token"])
        preview = await tool(kind)(c, data, 19723)
        await tool(kind)(c, data, 19723, False, preview["confirmation_token"])
        with pytest.raises(ValueError, match="already exists"):
            await tool(kind)(c, data)


@pytest.mark.parametrize("kind", ["folders", "clones"])
@pytest.mark.parametrize(
    "fault",
    [
        "lost",
        "malformed",
        "native_error",
        "ignored",
        "wrong_parent",
        "wrong_name",
        "old_changed",
        "read_lost",
    ],
)
async def test_dispatch_faults_and_readback(kind, fault):
    fake = FakeArchicad(19723)
    base = fake_transport(fake)
    command = "CreateViewMapFolder" if kind == "folders" else "CloneProjectMapItemToViewMap"
    writes = 0

    def handler(request):
        nonlocal writes
        body = json.loads(request.content)
        cmd = body.get("parameters", {}).get("addOnCommandId", {}).get("commandName")
        if cmd == command:
            writes += 1
            if fault == "native_error":
                return httpx.Response(
                    200,
                    json={
                        "succeeded": True,
                        "result": {
                            "addOnCommandResponse": {"error": {"code": -1, "message": "Refused"}}
                        },
                    },
                )
        response = base.handle_request(request)
        if cmd == command:
            if fault == "lost":
                raise httpx.ReadTimeout("Lost", request=request)
            if fault == "malformed":
                return httpx.Response(
                    200, json={"succeeded": True, "result": {"addOnCommandResponse": {}}}
                )
            args = body["parameters"]["addOnCommandParameters"]
            data = args if kind == "folders" else args["viewsData"][0]
            root = fake.navigator_trees["PublicViewMap"]
            parent = _view_map_node(root, data["parentNavigatorItemId"]["guid"])
            node = parent["children"][-1]["navigatorItem"]
            if fault == "ignored":
                parent["children"].pop()
            elif fault == "wrong_name":
                node["name"] = "Wrong"
            elif fault == "wrong_parent":
                moved = parent["children"].pop()
                other = _view_map_node(
                    root, FOLDER if data["parentNavigatorItemId"]["guid"] == ROOT else ROOT
                )
                other.setdefault("children", []).append(moved)
            elif fault == "old_changed":
                _view_map_node(root, VIEW)["name"] = "Changed"
        if cmd == "GetNavigatorItemTree" and writes and fault == "read_lost":
            raise httpx.ReadTimeout("Read lost", request=request)
        return response

    async with ArchicadClient(transport=httpx.MockTransport(handler)) as c:
        preview = await tool(kind)(c, entries(kind), 19723)
        result = await tool(kind)(c, entries(kind), 19723, False, preview["confirmation_token"])
    first, second = result["items"]
    if fault in ("lost", "malformed"):
        assert first["status"] == "unknown" and second["not_attempted"] and writes == 1
    elif fault == "read_lost":
        assert first["status"] == "unverified" and second["not_attempted"] and writes == 1
    elif fault == "native_error":
        assert all(i["status"] == "failed" for i in result["items"])
    else:
        assert first["status"] == "verification_failed"
    assert result["status"] == "needs_review"


@pytest.mark.parametrize("source_id", [None, "88888888-8888-4888-8888-000000000003"])
async def test_clone_source_guid_must_match_even_with_identical_name_and_type(source_id):
    """Name/type/uiId cannot distinguish clones of different Project Map viewpoints."""
    fake = FakeArchicad(19723)
    base = fake_transport(fake)

    def handler(request):
        response = base.handle_request(request)
        body = json.loads(request.content)
        cmd = body.get("parameters", {}).get("addOnCommandId", {}).get("commandName")
        if cmd == "CloneProjectMapItemToViewMap":
            parent = _view_map_node(fake.navigator_trees["PublicViewMap"], FOLDER)
            created = parent["children"][-1]["navigatorItem"]
            if source_id is None:
                created.pop("sourceNavigatorItemId")
            else:
                created["sourceNavigatorItemId"] = {"guid": source_id}
        return response

    async with ArchicadClient(transport=httpx.MockTransport(handler)) as c:
        data = entries("clones")[:1]
        preview = await navigator.clone_to_view_map(c, data, 19723)
        result = await navigator.clone_to_view_map(
            c, data, 19723, False, preview["confirmation_token"]
        )
    assert result["status"] == "needs_review"
    assert result["items"][0]["status"] == "verification_failed"
    assert "source_guid" in result["items"][0]["mismatches"]


@pytest.mark.parametrize("flag", ["customName", "customUiId", "isIndependent"])
async def test_changed_view_inheritance_flags_invalidate_preview(flag):
    fake = FakeArchicad(19723)
    data = entries("clones")[:1]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await navigator.clone_to_view_map(c, data, 19723)
        existing = _view_map_node(fake.navigator_trees["PublicViewMap"], VIEW)
        existing[flag] = not existing[flag]
        with pytest.raises(ValueError, match="changed"):
            await navigator.clone_to_view_map(c, data, 19723, False, preview["confirmation_token"])
    assert "CloneProjectMapItemToViewMap" not in fake.tapir_calls


async def test_project_map_container_is_not_previewed_as_one_viewpoint():
    fake = FakeArchicad(19723)
    source = _view_map_node(fake.navigator_trees["ProjectMap"], SOURCE)
    child = deepcopy(source)
    child["navigatorItemId"] = {"guid": "88888888-8888-4888-8888-000000000099"}
    source["children"] = [{"navigatorItem": child}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="Source"):
            await navigator.clone_to_view_map(c, entries("clones")[:1])
    assert "CloneProjectMapItemToViewMap" not in fake.tapir_calls


@pytest.mark.parametrize(
    "name",
    ["Before\x00After", "😀" * 128, "\ud800"],
    ids=["embedded-nul", "utf16-overflow", "invalid-unicode"],
)
async def test_folder_name_must_fit_native_unicode_buffer_without_embedded_nul(name):
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await navigator.create_view_map_folders(c, [{"parent_guid": ROOT, "name": name}])
    assert not fake.calls


async def test_folder_name_at_utf16_boundary_is_accepted_without_truncation():
    fake = FakeArchicad(19723)
    name = "😀" * 127 + "á"
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        data = [{"parent_guid": ROOT, "name": name}]
        preview = await navigator.create_view_map_folders(c, data, 19723)
        result = await navigator.create_view_map_folders(
            c, data, 19723, False, preview["confirmation_token"]
        )
    assert result["status"] == "verified"
    assert result["items"][0]["after"]["name"] == name


@pytest.mark.parametrize(
    "bad_source", [None, {}, {"guid": "bad"}, {"guid": "00000000-0000-0000-0000-000000000000"}]
)
async def test_malformed_source_identity_is_not_silently_discarded(bad_source):
    fake = FakeArchicad(19723)
    existing = _view_map_node(fake.navigator_trees["PublicViewMap"], VIEW)
    existing["sourceNavigatorItemId"] = bad_source
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="source ID"):
            await navigator.clone_to_view_map(c, entries("clones")[:1])
    assert "CloneProjectMapItemToViewMap" not in fake.tapir_calls
