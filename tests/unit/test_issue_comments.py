"""Tapir 1.7.0 comment protocol, simulated only; never accesses Archicad."""

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest

from archicad_mcp_aberto.connection import ArchicadClient
from archicad_mcp_aberto.tools import issues
from tests.unit.fake_archicad import COMMENTS_FIXTURE, FakeArchicad, fake_transport

pytestmark = pytest.mark.anyio
ISSUE = "99999999-9999-4999-8999-999999999999"
MISSING = "11111111-1111-4111-8111-111111111111"


@pytest.fixture(autouse=True)
def receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCHICAD_MCP_RECEIPTS_DIR", str(tmp_path))


def entry(**changes):
    return {"issue_guid": ISSUE, "text": "Conferir porta", **changes}


async def apply(client, entries):
    preview = await issues.add_comment_to_issue(client, entries, 19723)
    return await issues.add_comment_to_issue(
        client, entries, 19723, False, preview["confirmation_token"]
    )


async def test_preview_apply_duplicate_text_distinct_guids_and_receipt():
    fake = FakeArchicad(19723)
    entries = [entry(), entry(), entry(author="Vitor")]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await issues.add_comment_to_issue(c, entries)
        assert preview["dry_run"] and not fake.issue_comments
        token = preview["confirmation_token"]
        result = await issues.add_comment_to_issue(c, entries, 19723, False, token)
        with pytest.raises(ValueError, match="consumed"):
            await issues.add_comment_to_issue(c, entries, 19723, False, token)
    assert result["status"] == "verified"
    assert len({i["comment_guid"] for i in result["items"]}) == 3
    assert [r["author"] for r in fake.issue_comments[ISSUE]] == ["API", "API", "Vitor"]
    assert all(i["comment_receipt_id"] for i in result["items"])
    saved = json.loads(Path(result["receipt_path"]).read_text())
    assert saved["counts"]["verified"] == 3
    assert not any("Save" in n or "Delete" in n or "Attach" in n for n in fake.tapir_calls)
    parameters = [
        r["parameters"] for r in fake.tapir_requests if r["command"] == "AddCommentToIssue"
    ]
    assert parameters[0] == {"issueId": {"guid": ISSUE}, "text": entries[0]["text"]}


async def test_maximum_twenty_comment_batch():
    fake = FakeArchicad(19723)
    comments = [entry(text=f"Comentário {index}") for index in range(20)]
    async with ArchicadClient(transport=fake_transport(fake)) as client:
        result = await apply(client, comments)
    assert result["counts"]["verified"] == 20
    assert fake.tapir_calls.count("AddCommentToIssue") == 20


@pytest.mark.parametrize(
    "entries",
    [
        [],
        [entry()] * 21,
        [entry(text=" ")],
        [entry(author=" ")],
        [entry(text="")],
        [entry(issue_guid="bad")],
        [entry(issue_guid="00000000-0000-0000-0000-000000000000")],
        [entry(status="Error")],
        [entry(text=1)],
    ],
)
async def test_invalid_inputs_before_network(entries):
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError):
            await issues.add_comment_to_issue(c, entries)
    assert not fake.calls


async def test_missing_issue_explicit_port_and_unknown_token():
    fake = FakeArchicad(19723)
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        with pytest.raises(ValueError, match="does not exist"):
            await issues.add_comment_to_issue(c, [entry(issue_guid=MISSING)])
        preview = await issues.add_comment_to_issue(c, [entry()])
        with pytest.raises(ValueError, match="explicit port"):
            await issues.add_comment_to_issue(
                c, [entry()], None, False, preview["confirmation_token"]
            )
        with pytest.raises(ValueError, match="missing"):
            await issues.add_comment_to_issue(c, [entry()], 19723, False, "bad")
    assert not fake.issue_comments


@pytest.mark.parametrize("change", ["text", "author", "issue", "comments", "project"])
async def test_stale_preview_rejected(change):
    fake = FakeArchicad(19723)
    entries = [entry()]
    async with ArchicadClient(transport=fake_transport(fake)) as c:
        preview = await issues.add_comment_to_issue(c, entries, 19723)
        if change in ("text", "author"):
            entries = [entry(**{change: "Changed"})]
        elif change == "issue":
            fake.issues[ISSUE]["name"] = "Changed"
        elif change == "comments":
            fake.issue_comments[ISSUE] = [deepcopy(COMMENTS_FIXTURE["comment"])]
        else:
            fake.project_name = "Other"
        with pytest.raises(ValueError, match="changed"):
            await issues.add_comment_to_issue(
                c, entries, 19723, False, preview["confirmation_token"]
            )
    assert "AddCommentToIssue" not in fake.tapir_calls


@pytest.mark.parametrize(
    "fault",
    [
        "lost",
        "malformed",
        "failed",
        "ignored",
        "wrong_text",
        "wrong_author",
        "duplicate_guid",
        "old_changed",
        "read_lost",
    ],
)
async def test_dispatch_failures_and_independent_readback(fault):
    fake = FakeArchicad(19723)
    fake.issue_comments[ISSUE] = [deepcopy(COMMENTS_FIXTURE["comment"])]
    base = fake_transport(fake)
    writes = 0

    def handler(request):
        nonlocal writes
        body = json.loads(request.content)
        cmd = body.get("parameters", {}).get("addOnCommandId", {}).get("commandName")
        if cmd == "AddCommentToIssue":
            writes += 1
            if fault == "failed":
                return httpx.Response(
                    200,
                    json={
                        "succeeded": True,
                        "result": {"addOnCommandResponse": COMMENTS_FIXTURE["failed"]},
                    },
                )
        response = base.handle_request(request)
        if cmd == "AddCommentToIssue":
            if fault == "lost":
                raise httpx.ReadTimeout("Lost after writing", request=request)
            if fault == "malformed":
                return httpx.Response(
                    200, json={"succeeded": True, "result": {"addOnCommandResponse": {}}}
                )
            if fault == "ignored":
                fake.issue_comments[ISSUE].pop()
            if fault in ("wrong_text", "wrong_author"):
                fake.issue_comments[ISSUE][-1][fault.removeprefix("wrong_")] = "Wrong"
            if fault == "duplicate_guid":
                fake.issue_comments[ISSUE][-1]["guid"] = fake.issue_comments[ISSUE][0]["guid"]
            if fault == "old_changed":
                fake.issue_comments[ISSUE][0]["text"] = "Changed existing"
        if cmd == "GetCommentsFromIssue" and writes and fault == "read_lost":
            raise httpx.ReadTimeout("Read-back lost", request=request)
        return response

    async with ArchicadClient(transport=httpx.MockTransport(handler)) as c:
        result = await apply(c, [entry(), entry()])
    first, second = result["items"]
    if fault in ("lost", "malformed"):
        assert first["status"] == "unknown" and second["not_attempted"]
        assert writes == 1
    elif fault == "failed":
        assert [i["status"] for i in result["items"]] == ["failed", "failed"]
    elif fault in ("duplicate_guid", "read_lost"):
        assert first["status"] == "unverified" and second["not_attempted"]
        assert writes == 1
    else:
        assert first["status"] == "verification_failed"
        assert second["not_attempted"] and writes == 1
    assert result["status"] == "needs_review"


async def test_multiple_instances_require_selection():
    from archicad_mcp_aberto.connection.errors import AmbiguousTarget

    async with ArchicadClient(
        transport=fake_transport(FakeArchicad(19723), FakeArchicad(19724))
    ) as c:
        with pytest.raises(AmbiguousTarget):
            await issues.add_comment_to_issue(c, [entry()])


async def test_project_change_between_comments_stops_remaining_writes():
    """A copied project can retain issue GUIDs, so GUID read-back alone is insufficient."""
    fake = FakeArchicad(19723)
    base = fake_transport(fake)
    writes = 0

    def handler(request):
        nonlocal writes
        body = json.loads(request.content)
        command = body.get("parameters", {}).get("addOnCommandId", {}).get("commandName")
        if command == "AddCommentToIssue":
            writes += 1
        response = base.handle_request(request)
        if command == "GetCommentsFromIssue" and writes == 1:
            fake.project_name = "Copied project"
        return response

    async with ArchicadClient(transport=httpx.MockTransport(handler)) as client:
        result = await apply(client, [entry(), entry(text="Segundo comentário")])

    assert result["items"][0]["status"] == "verified"
    assert result["items"][1]["not_attempted"]
    assert "context changed" in result["context_error"]
    assert writes == 1


async def test_concurrent_comment_between_items_stops_remaining_writes():
    fake = FakeArchicad(19723)
    base = fake_transport(fake)
    writes = 0
    inserted = False

    def handler(request):
        nonlocal inserted, writes
        body = json.loads(request.content)
        command = body.get("parameters", {}).get("addOnCommandId", {}).get("commandName")
        if command == "AddCommentToIssue":
            writes += 1
        response = base.handle_request(request)
        if command == "GetCommentsFromIssue" and writes == 1 and not inserted:
            fake.issue_comments[ISSUE].append(deepcopy(COMMENTS_FIXTURE["comment"]))
            inserted = True
        return response

    async with ArchicadClient(transport=httpx.MockTransport(handler)) as client:
        result = await apply(client, [entry(), entry(text="Segundo comentário")])

    assert result["items"][0]["status"] == "verified"
    assert result["items"][1]["not_attempted"]
    assert writes == 1
