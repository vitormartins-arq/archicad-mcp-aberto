import json
from copy import deepcopy

import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import write
from tests.unit.fake_archicad import FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
GUID = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))
    return tmp_path


def model(**kwargs):
    return FakeArchicad(
        19723,
        project_name="",
        elements={GUID: "Wall", OTHER: "Slab"},
        details={
            GUID: {"type": "Wall", "floorIndex": 0, "layerIndex": 1},
            OTHER: {"type": "Slab", "floorIndex": 0, "layerIndex": 2},
        },
        **kwargs,
    )


async def apply(c, ids):
    preview = await write.delete_elements(c, ids, 19723)
    return await write.delete_elements(c, ids, 19723, False, preview["confirmation_token"])


async def test_preview_then_delete_receipts_and_single_use(receipts):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await write.delete_elements(c, [GUID])
        assert preview["dry_run"] is True
        assert preview["items"][0]["before"] == {"type": "Wall", "floorIndex": 0, "layerIndex": 1}
        assert "DeleteElements" not in fake.tapir_calls
        result = await write.delete_elements(c, [GUID], 19723, False, preview["confirmation_token"])
        with pytest.raises(ValueError, match="consumed"):
            await write.delete_elements(c, [GUID], 19723, False, preview["confirmation_token"])
    assert result["status"] == "verified"
    assert result["items"][0]["after"] == {"exists": False}
    assert set(fake.elements) == {OTHER}
    assert len(list(receipts.glob("*.json"))) == 2
    assert all("Save" not in command for command in fake.calls + fake.tapir_calls)


@pytest.mark.parametrize("reason", ["named", "missing", "hotlink", "locked", "missing-layer"])
async def test_preflight_refuses_unsafe_targets(reason):
    fake = model()
    if reason == "named":
        fake.project_name = "Real project"
    elif reason == "missing":
        del fake.elements[GUID]
    elif reason == "hotlink":
        fake.details[GUID]["hotlinkId"] = {"guid": OTHER}
    elif reason == "locked":
        fake.locked_elements.add(GUID)
    else:
        del fake.details[GUID]["layerIndex"]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await write.delete_elements(c, [GUID], 19723)
    assert "DeleteElements" not in fake.tapir_calls


@pytest.mark.parametrize("ids", [[], [GUID] * 51, [GUID, GUID], ["bad-guid"]])
async def test_invalid_input_without_requests(ids):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await write.delete_elements(c, ids)
    assert fake.calls == []


async def test_requires_port_and_unchanged_plan():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await write.delete_elements(c, [GUID], 19723)
        with pytest.raises(ValueError, match="explicit port"):
            await write.delete_elements(
                c, [GUID], dry_run=False, confirmation_token=preview["confirmation_token"]
            )
        with pytest.raises(ValueError, match="changed"):
            await write.delete_elements(c, [OTHER], 19723, False, preview["confirmation_token"])
        fake.project_name = "Named now"
        with pytest.raises(ValueError, match="untitled"):
            await write.delete_elements(c, [GUID], 19723, False, preview["confirmation_token"])
    assert "DeleteElements" not in fake.tapir_calls


async def test_lock_added_after_preview_refused():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await write.delete_elements(c, [GUID], 19723)
        fake.locked_elements.add(GUID)
        with pytest.raises(ValueError, match="Locked"):
            await write.delete_elements(c, [GUID], 19723, False, preview["confirmation_token"])
    assert GUID in fake.elements


async def test_project_change_after_journaling_prevents_delete(monkeypatch):
    fake = model()
    original = write._journal

    def journal(receipt, phase):
        path = original(receipt, phase)
        if phase == "prepared":
            fake.project_name = "Changed after preview"
        return path

    monkeypatch.setattr(write, "_journal", journal)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [GUID])
    assert result["items"][0]["status"] == "failed"
    assert "DeleteElements" not in fake.tapir_calls
    assert GUID in fake.elements


async def test_partial_error_preserves_other_item():
    fake = model(delete_errors={1: {"success": False, "error": {"code": -1, "message": "Locked"}}})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [GUID, OTHER])
    assert [i["status"] for i in result["items"]] == ["verified", "failed"]
    assert set(fake.elements) == {OTHER}
    assert len({i["delete_receipt_id"] for i in result["items"]}) == 2


async def test_silent_skipped_delete_fails_verification():
    fake = model(delete_ignored=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [GUID])
    assert result["items"][0]["status"] == "verification_failed"
    assert result["items"][0]["after"] == {"exists": True}


async def test_lost_response_unknown_no_retry():
    fake = model(lose_delete_response=True)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await write.delete_elements(c, [GUID], 19723)
        result = await write.delete_elements(c, [GUID], 19723, False, preview["confirmation_token"])
        with pytest.raises(ValueError, match="consumed"):
            await write.delete_elements(c, [GUID], 19723, False, preview["confirmation_token"])
    assert result["items"][0]["status"] == "unknown"
    assert GUID not in fake.elements
    assert fake.tapir_calls.count("DeleteElements") == 1


async def test_journal_failure_prevents_write(monkeypatch):
    fake = model()

    def fail(*args):
        raise OSError("disk full")

    monkeypatch.setattr(write, "_journal", fail)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(OSError):
            await apply(c, [GUID])
    assert "DeleteElements" not in fake.tapir_calls


async def test_malformed_response_unknown(monkeypatch):
    original = FakeArchicad._tapir

    def malformed(self, params):
        result = original(self, params)
        if params["addOnCommandId"]["commandName"] == "DeleteElements":
            return {"succeeded": True, "result": {"addOnCommandResponse": {}}}
        return deepcopy(result)

    monkeypatch.setattr(FakeArchicad, "_tapir", malformed)
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [GUID])
    assert result["items"][0]["status"] == "unknown"


async def test_verification_error_is_unverified(monkeypatch):
    original = FakeArchicad.handle

    def fail_verification(self, body):
        if body["command"] == "API.GetAllElements" and "DeleteElements" in self.tapir_calls:
            return {"succeeded": True, "result": {}}
        return original(self, body)

    monkeypatch.setattr(FakeArchicad, "handle", fail_verification)
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [GUID])
    assert result["items"][0]["status"] == "unverified"
    assert result["verification_error"]


async def test_receipt_records_documented_transport(receipts):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await apply(c, [GUID])
    journal = json.loads(next(receipts.glob("*.result.json")).read_text(encoding="utf-8"))
    assert journal["operation"] == result["operation"] == "delete_elements"
    assert "API.DeleteElements" not in fake.calls
    assert "FilterElements" in fake.tapir_calls
