"""IssueCommands tag 1.7.0 fixtures; all tests use MockTransport, never Archicad."""

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import issues
from tests.unit.fake_archicad import ISSUES_FIXTURE, FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
ISSUE = "99999999-9999-4999-8999-999999999999"
FIRST = "11111111-1111-1111-1111-111111111111"
SECOND = "22222222-2222-2222-2222-222222222222"
THIRD = "33333333-3333-3333-3333-333333333333"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def model(**kwargs):
    return FakeArchicad(19723, elements={FIRST: "Wall", SECOND: "Slab", THIRD: "Column"}, **kwargs)


async def create(c, entries):
    preview = await issues.create_issues(c, entries, 19723)
    return await issues.create_issues(c, entries, 19723, False, preview["confirmation_token"])


async def attach(c, guids):
    preview = await issues.attach_elements_to_issue(c, ISSUE, guids, 19723)
    return await issues.attach_elements_to_issue(
        c, ISSUE, guids, 19723, False, preview["confirmation_token"]
    )


async def test_list_filter_and_pagination():
    fake = model()
    other = deepcopy(fake.issues[ISSUE])
    other.update(issueId={"guid": FIRST}, name="Structure", tagText="URGENT")
    fake.issues[FIRST] = other
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await issues.list_issues(c, 19723)
        assert result["total"] == 2
        assert result["issues"][0]["guid"] == ISSUE
        assert (
            result["issues"][0]["parentIssueId"]
            == ISSUES_FIXTURE["get_issues"]["issues"][0]["parentIssueId"]
        )
        filtered = await issues.list_issues(c, 19723, query="urgent")
        assert [i["guid"] for i in filtered["issues"]] == [FIRST]
        page = await issues.list_issues(c, 19723, offset=1, limit=1)
        assert page["total"] == 2 and len(page["issues"]) == 1
        assert not (await issues.list_issues(c, 19723, offset=9))["issues"]
    assert set(fake.tapir_calls) == {"GetIssues"}


@pytest.mark.parametrize("arguments", [{"offset": -1}, {"limit": 0}, {"limit": 501}])
async def test_list_invalid_page_before_network(arguments):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await issues.list_issues(c, **arguments)
    assert not fake.calls


async def test_create_preview_apply_receipts_and_one_use_token():
    fake = model()
    entries = [{"name": "Door clash", "tagText": "Review today"}, {"name": "Missing finish"}]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await issues.create_issues(c, entries, 19723)
        assert "CreateIssue" not in fake.tapir_calls and len(fake.issues) == 1
        result = await issues.create_issues(c, entries, 19723, False, preview["confirmation_token"])
        with pytest.raises(ValueError, match="consumed"):
            await issues.create_issues(c, entries, 19723, False, preview["confirmation_token"])
    assert result["status"] == "verified"
    assert len(fake.issues) == 3
    assert all(i["issue_receipt_id"] and i["issue_guid"] for i in result["items"])
    assert result["items"][0]["after"]["name"] == "Door clash"
    assert result["items"][1]["after"]["tagText"] == ""
    journal = json.loads(Path(result["receipt_path"]).read_text(encoding="utf-8"))
    assert journal["counts"]["verified"] == 2
    assert [
        r["parameters"] for r in fake.tapir_requests if r["command"] == "CreateIssue"
    ] == entries
    assert not any("Save" in cmd or "Delete" in cmd or "BCF" in cmd for cmd in fake.tapir_calls)


@pytest.mark.parametrize(
    "entries",
    [
        [],
        [{"name": "A"}] * 21,
        [{"name": " "}],
        [{"name": "A", "parentIssueId": {"guid": ISSUE}}],
        [{"name": "A", "tagText": 123}],
    ],
)
async def test_invalid_create_before_network(entries):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await issues.create_issues(c, entries)
    assert not fake.calls


async def test_create_maximum_twenty():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = await create(c, [{"name": f"Issue {i}"} for i in range(20)])
    assert result["counts"]["verified"] == 20


@pytest.mark.parametrize("operation", ["create", "attach"])
async def test_known_native_error_is_per_item(operation):
    command = "CreateIssue" if operation == "create" else "AttachElementsToIssue"
    failure = ISSUES_FIXTURE["create_error" if operation == "create" else "attach_error"]
    fake = model(issue_errors={command: {1: failure}})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = (
            await create(c, [{"name": "A"}, {"name": "B"}, {"name": "C"}])
            if operation == "create"
            else await attach(c, [FIRST, SECOND, THIRD])
        )
    assert [i["status"] for i in result["items"]] == ["verified", "failed", "verified"]
    assert result["items"][1]["error"]["code"] == -1
    assert fake.tapir_calls.count(command) == 3


@pytest.mark.parametrize("operation", ["create", "attach"])
async def test_success_without_change_fails_readback(operation):
    command = "CreateIssue" if operation == "create" else "AttachElementsToIssue"
    fake = model(issue_ignored={command})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        result = (
            await create(c, [{"name": "A"}]) if operation == "create" else await attach(c, [FIRST])
        )
    assert result["items"][0]["status"] == "verification_failed"
    assert result["items"][0]["mismatches"]


async def test_attach_reads_back_every_element_and_preserves_existing_links():
    fake = model(issue_attachments={ISSUE: {THIRD}})
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await issues.attach_elements_to_issue(c, ISSUE.lower(), [FIRST, SECOND], 19723)
        assert "AttachElementsToIssue" not in fake.tapir_calls
        assert preview["target"]["highlight_elements"] == [THIRD]
        result = await issues.attach_elements_to_issue(
            c, ISSUE, [FIRST, SECOND], 19723, False, preview["confirmation_token"]
        )
        again = await attach(c, [FIRST])
        assert again["items"][0]["already_attached"]
    assert result["status"] == "verified"
    assert fake.issue_attachments[ISSUE] == {FIRST, SECOND, THIRD}
    assert all(i["issue_attachment_receipt_id"] for i in result["items"])
    sent = [r["parameters"] for r in fake.tapir_requests if r["command"] == "AttachElementsToIssue"]
    assert sent[0] == {
        "issueId": {"guid": ISSUE},
        "type": "Highlight",
        "elements": [{"elementId": {"guid": FIRST}}],
    }
    assert all(r["type"] == "Highlight" for r in sent)


@pytest.mark.parametrize(
    "guid, elements",
    [
        ("bad", [FIRST]),
        (ISSUE, []),
        (ISSUE, [FIRST] * 101),
        (ISSUE, [FIRST, FIRST]),
        (ISSUE, ["bad"]),
    ],
)
async def test_attach_invalid_input_before_network(guid, elements):
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await issues.attach_elements_to_issue(c, guid, elements)
    assert not fake.calls


@pytest.mark.parametrize("reason", ["missing-issue", "missing-element"])
async def test_missing_target_refused_in_preview(reason):
    fake = model()
    if reason == "missing-issue":
        fake.issues.clear()
    else:
        fake.elements.pop(SECOND)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="does not exist"):
            await issues.attach_elements_to_issue(c, ISSUE, [FIRST, SECOND], 19723)
    assert "AttachElementsToIssue" not in fake.tapir_calls
    assert not fake.issue_attachments


@pytest.mark.parametrize("operation", ["create", "attach"])
async def test_apply_port_token_and_snapshot_binding(operation):
    fake = model()
    tool = issues.create_issues if operation == "create" else issues.attach_elements_to_issue
    args = ([{"name": "A"}],) if operation == "create" else (ISSUE, [FIRST])
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await tool(c, *args, port=19723)
        token = preview["confirmation_token"]
        with pytest.raises(ValueError, match="explicit port"):
            await tool(c, *args, dry_run=False, confirmation_token=token)
        fake.issues[ISSUE]["name"] = "Externally changed"
        with pytest.raises(ValueError, match="changed"):
            await tool(c, *args, port=19723, dry_run=False, confirmation_token=token)
    assert not any(c in ("CreateIssue", "AttachElementsToIssue") for c in fake.tapir_calls)


async def test_attachment_set_change_requires_new_preview():
    fake = model()
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await issues.attach_elements_to_issue(c, ISSUE, [FIRST], 19723)
        fake.issue_attachments[ISSUE] = {SECOND}
        with pytest.raises(ValueError, match="changed"):
            await issues.attach_elements_to_issue(
                c, ISSUE, [FIRST], 19723, False, preview["confirmation_token"]
            )
    assert "AttachElementsToIssue" not in fake.tapir_calls


@pytest.mark.parametrize("operation", ["create", "attach"])
async def test_lost_second_response_verifies_prior_success_stops_and_consumes(operation):
    fake = model(lose_issue_response_at=2)
    tool = issues.create_issues if operation == "create" else issues.attach_elements_to_issue
    args = (
        ([{"name": "A"}, {"name": "B"}, {"name": "C"}],)
        if operation == "create"
        else (ISSUE, [FIRST, SECOND, THIRD])
    )
    command = "CreateIssue" if operation == "create" else "AttachElementsToIssue"
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await tool(c, *args, port=19723)
        result = await tool(
            c, *args, port=19723, dry_run=False, confirmation_token=preview["confirmation_token"]
        )
        with pytest.raises(ValueError, match="consumed"):
            await tool(
                c,
                *args,
                port=19723,
                dry_run=False,
                confirmation_token=preview["confirmation_token"],
            )
    assert [i["status"] for i in result["items"]] == ["verified", "unknown", "failed"]
    assert result["items"][2]["not_attempted"]
    assert fake.tapir_calls.count(command) == 2
    assert "Never retry" in result["warning"]


async def test_shared_write_timeout(monkeypatch):
    fake = model()
    timeouts = []

    class RecordingClient(ArchicadClient):
        async def tapir(self, port, name, parameters=None, *, timeout=None):
            if name in ("CreateIssue", "AttachElementsToIssue") or timeout is not None:
                timeouts.append((name, timeout))
            return await super().tapir(port, name, parameters, timeout=timeout)

    monkeypatch.setenv("ARCHICAD_MCP_WRITE_TIMEOUT", "45")
    async with RecordingClient(transport=fake_transport(fake)) as c:
        result = await create(c, [{"name": "A"}])
    assert result["write_timeout_seconds"] == 45
    assert ("CreateIssue", 45) in timeouts and ("GetIssues", 45) in timeouts


@pytest.mark.parametrize("command", ["CreateIssue", "AttachElementsToIssue"])
async def test_malformed_write_response_stops_and_unknown(command):
    fake = model()

    def handler(request):
        body = json.loads(request.content)
        response = fake.handle(body)
        if body.get("parameters", {}).get("addOnCommandId", {}).get("commandName") == command:
            return httpx.Response(
                200, json={"succeeded": True, "result": {"addOnCommandResponse": {}}}
            )
        return httpx.Response(200, json=response)

    tool = issues.create_issues if command == "CreateIssue" else issues.attach_elements_to_issue
    args = (
        ([{"name": "A"}, {"name": "B"}],) if command == "CreateIssue" else (ISSUE, [FIRST, SECOND])
    )
    async with ArchicadClient(transport=httpx.MockTransport(handler)) as c:
        preview = await tool(c, *args, port=19723)
        result = await tool(
            c, *args, port=19723, dry_run=False, confirmation_token=preview["confirmation_token"]
        )
    assert result["items"][0]["status"] == "unknown"
    assert result["items"][1]["not_attempted"]


async def test_old_issue_id_response_is_not_claimed_as_a_new_creation():
    fake = model()

    def handler(request):
        body = json.loads(request.content)
        response = fake.handle(body)
        if body.get("parameters", {}).get("addOnCommandId", {}).get("commandName") == "CreateIssue":
            response["result"]["addOnCommandResponse"] = {"issueId": {"guid": ISSUE}}
        return httpx.Response(200, json=response)

    async with ArchicadClient(transport=httpx.MockTransport(handler)) as c:
        result = await create(c, [{"name": "A"}, {"name": "B"}])
    assert result["items"][0]["status"] == "unknown"
    assert result["items"][1]["not_attempted"]
    assert fake.tapir_calls.count("CreateIssue") == 1


async def test_verification_failure_does_not_change_known_write_into_verified():
    fake = model()
    writes = False

    def handler(request):
        nonlocal writes
        body = json.loads(request.content)
        command = body.get("parameters", {}).get("addOnCommandId", {}).get("commandName")
        response = fake.handle(body)
        if command == "CreateIssue":
            writes = True
        if writes and command == "GetIssues":
            response["result"]["addOnCommandResponse"] = {"issues": "malformed"}
        return httpx.Response(200, json=response)

    async with ArchicadClient(transport=httpx.MockTransport(handler)) as c:
        result = await create(c, [{"name": "A"}])
    assert result["items"][0]["status"] == "unverified"
    assert result["status"] == "needs_review" and result["verification_error"]


async def test_prepared_receipt_failure_prevents_all_writes(monkeypatch):
    from archicad_mcp_aberto.tools import write

    fake = model()

    def denied(*args):
        raise OSError("Receipt unavailable")

    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await issues.create_issues(c, [{"name": "A"}], 19723)
        monkeypatch.setattr(write, "_journal", denied)
        with pytest.raises(OSError, match="Receipt unavailable"):
            await issues.create_issues(
                c, [{"name": "A"}], 19723, False, preview["confirmation_token"]
            )
    assert "CreateIssue" not in fake.tapir_calls
