"""Issue metadata and non-destructive Highlight associations (Tapir 1.7.0).

CreateIssue and AttachElementsToIssue are singular commands. Each response is retained
per item; a lost or malformed response stops the remaining writes, without retrying.
All writes share the existing preview/token/port/receipt protocol. Never saves or deletes.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Annotated, Any
from uuid import UUID

from pydantic import Field, field_validator

from archicad_mcp_aberto.connection import (
    ArchicadClient,
    ArchicadError,
    CommandFailed,
    TapirError,
    resolve_port,
)
from archicad_mcp_aberto.tools import read, write

MAX_ISSUES = 20
MAX_ELEMENTS = 100


def _guid(value: Any) -> str | None:
    value = value.get("guid") if isinstance(value, dict) else value
    try:
        return str(UUID(value)).upper()
    except (ValueError, TypeError, AttributeError):
        return None


class IssueCreate(write.InputModel):
    name: Annotated[str, Field(min_length=1, max_length=255)]
    tagText: Annotated[str, Field(max_length=2000)] | None = None

    @field_validator("name")
    @classmethod
    def visible(cls, value):
        if not value.strip():
            raise ValueError("Issue name must not be blank.")
        return value


class _Attachment(write.InputModel):
    issue_guid: str
    element_guid: str

    @field_validator("issue_guid", "element_guid")
    @classmethod
    def canonical_guid(cls, value):
        return str(UUID(value)).upper()


async def _rows(client, port, timeout=None):
    result = await client.tapir(port, "GetIssues", timeout=timeout)
    rows = result.get("issues")
    if not isinstance(rows, list):
        raise ValueError("Unexpected GetIssues response.")
    out = []
    for row in rows:
        guid = _guid(row.get("issueId")) if isinstance(row, dict) else None
        if (
            not guid
            or not isinstance(row.get("name"), str)
            or not isinstance(row.get("tagText"), str)
        ):
            raise ValueError("Unexpected issue metadata.")
        out.append({**row, "guid": guid})
    if len({r["guid"] for r in out}) != len(out):
        raise ValueError("Duplicate issue GUID in GetIssues response.")
    return out


async def _attached(client, port, issue_guid, timeout=None):
    result = await client.tapir(
        port,
        "GetElementsAttachedToIssue",
        {"issueId": {"guid": issue_guid}, "type": "Highlight"},
        timeout=timeout,
    )
    rows = result.get("elements")
    if not isinstance(rows, list):
        raise ValueError("Unexpected issue attachment response.")
    guids = []
    for row in rows:
        guid = _guid(row.get("elementId")) if isinstance(row, dict) else None
        if not guid:
            raise ValueError("Unexpected attached element ID.")
        guids.append(guid)
    return sorted(set(guids))


async def list_issues(
    client: ArchicadClient,
    port: int | None = None,
    query: str | None = None,
    offset: int = 0,
    limit: int = 200,
) -> dict:
    """List issues, optionally filtering name/tagText; offset/limit apply after filtering."""
    read.page_args(offset, limit, 500)
    port = await resolve_port(client, port)
    rows = await _rows(client, port)
    if query:
        text = query.casefold()
        rows = [r for r in rows if text in r["name"].casefold() or text in r["tagText"].casefold()]
    return {
        "port": port,
        "issues": rows[offset : offset + limit],
        "total": len(rows),
        "offset": offset,
        "limit": limit,
    }


async def _plan(client, entries, port, operation):
    port, target, _ = await write._context(client, port)
    issues = await _rows(client, port)
    # Issue metadata is not part of GetAllElements; bind it separately to confirmation.
    target["issues_digest"] = write._digest(sorted(issues, key=lambda r: r["guid"]))
    target["issue_guids"] = sorted(r["guid"] for r in issues)
    if operation == "create_issues":
        items = [
            {"index": i, "status": "ready", "parameters": e.model_dump(exclude_none=True)}
            for i, e in enumerate(entries)
        ]
    else:
        issue_guid = entries[0].issue_guid
        issue = next((r for r in issues if r["guid"] == issue_guid), None)
        if issue is None:
            raise ValueError(f"Issue {issue_guid} does not exist.")
        existing = await _attached(client, port, issue_guid)
        guids = [e.element_guid for e in entries]
        result = await client.tapir(
            port,
            "GetDetailsOfElements",
            {
                "elements": read.element_ids(guids),
                "fields": write.DETAIL_FIELDS,
            },
        )
        rows = result.get("detailsOfElements")
        if not isinstance(rows, list) or len(rows) != len(guids):
            raise ValueError("Unexpected element details response.")
        items = []
        for i, (entry, row) in enumerate(zip(entries, rows, strict=True)):
            if not isinstance(row, dict) or "error" in row or row.get("type") in (None, "Unknown"):
                raise ValueError(f"Element {entry.element_guid} does not exist or cannot be read.")
            items.append(
                {
                    "index": i,
                    "status": "ready",
                    "issue_guid": issue_guid,
                    "issue_name": issue["name"],
                    "element_guid": entry.element_guid,
                    "before": deepcopy(row),
                    "already_attached": entry.element_guid in existing,
                    "parameters": {
                        "issueId": {"guid": issue_guid},
                        "type": "Highlight",
                        "elements": read.element_ids([entry.element_guid]),
                    },
                }
            )
        target["highlight_elements"] = existing
    return {"operation": operation, "target": target, "items": items}


def _unknown(receipt, index, error):
    items = receipt["items"]
    items[index].update(status="unknown", error=str(error))
    for item in items[index + 1 :]:
        item.update(
            status="failed",
            not_attempted=True,
            error="Not attempted after an unknown outcome; run a new preview after inspection.",
        )
    receipt["warning"] = (
        "Outcome unknown for this item; later writes stopped. Never retry this token."
    )


async def _dispatch(client, receipt):
    port, timeout = receipt["target"]["port"], receipt["write_timeout_seconds"]
    creating = receipt["operation"] == "create_issues"
    command = "CreateIssue" if creating else "AttachElementsToIssue"
    receipt["undo_scope"] = "Each issue or association is a separate native command and Undo step."
    good = []
    known = set(receipt["target"]["issue_guids"])
    for index, item in enumerate(receipt["items"]):
        try:
            raw = await client.tapir(port, command, item["parameters"], timeout=timeout)
        except (TapirError, CommandFailed) as exc:
            # Only a documented explicit rejection is known to have failed.
            if isinstance(exc.detail, dict) and "code" in exc.detail and "message" in exc.detail:
                item.update(status="failed", error=exc.detail)
                continue
            _unknown(receipt, index, exc)
            break
        except ArchicadError as exc:
            _unknown(receipt, index, exc)
            break
        item["write_response"] = raw
        if creating:
            guid = _guid(raw.get("issueId"))
            if not guid or UUID(guid).int == 0 or guid in known:
                _unknown(receipt, index, "Missing or duplicate created issue GUID.")
                break
            known.add(guid)
            item["issue_guid"] = guid
        elif raw.get("success") is False and isinstance(raw.get("error"), dict):
            item.update(status="failed", error=raw["error"])
            continue
        elif raw.get("success") is not True:
            _unknown(receipt, index, "Unexpected attachment execution result.")
            break
        item["status"] = "unverified"
        good.append(item)
    if not good:
        return
    try:
        issues = {r["guid"]: r for r in await _rows(client, port, timeout)}
        attached = (
            None if creating else await _attached(client, port, good[0]["issue_guid"], timeout)
        )
    except (ArchicadError, ValueError) as exc:
        receipt["verification_error"] = str(exc)
        return
    for item in good:
        issue = issues.get(item["issue_guid"])
        differences = []
        if creating:
            item["after"] = issue
            if issue is None:
                differences.append("issue_missing")
            else:
                for key in ("name", "tagText"):
                    if issue[key] != item["parameters"].get(key, ""):
                        differences.append(key)
        else:
            item["after"] = {"issue": issue, "attached": item["element_guid"] in attached}
            if issue is None:
                differences.append("issue_missing")
            if not item["after"]["attached"]:
                differences.append("element_not_attached")
        item["status"] = "verification_failed" if differences else "verified"
        if differences:
            item["mismatches"] = differences


async def create_issues(
    client: ArchicadClient,
    issues: list[dict | IssueCreate],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/create up to 20 issues: name and optional tagText. No BCF, save or delete."""
    if not 1 <= len(issues) <= MAX_ISSUES:
        raise ValueError(f"Pass between 1 and {MAX_ISSUES} issues.")
    entries = [e if isinstance(e, IssueCreate) else IssueCreate.model_validate(e) for e in issues]
    return await write._write(
        client,
        entries,
        port,
        dry_run,
        confirmation_token,
        "create_issues",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )


class IssueComment(write.InputModel):
    issue_guid: str
    text: Annotated[str, Field(min_length=1, max_length=10000)]
    author: Annotated[str, Field(min_length=1, max_length=255)] | None = None

    @field_validator("issue_guid")
    @classmethod
    def valid_guid(cls, value):
        guid = UUID(value)
        if guid.int == 0:
            raise ValueError("Issue GUID must not be null.")
        return str(guid).upper()

    @field_validator("text", "author")
    @classmethod
    def visible(cls, value):
        if value is not None and not value.strip():
            raise ValueError("Comment text and author must not be blank.")
        return value


async def _comments(client, port, issue_guid, timeout=None):
    raw = await client.tapir(
        port, "GetCommentsFromIssue", {"issueId": {"guid": issue_guid}}, timeout=timeout
    )
    rows = raw.get("comments")
    if not isinstance(rows, list):
        raise ValueError("Unexpected comments response.")
    seen = set()
    for row in rows:
        guid = _guid(row.get("guid")) if isinstance(row, dict) else None
        if (
            not guid
            or UUID(guid).int == 0
            or guid in seen
            or not isinstance(row.get("text"), str)
            or not isinstance(row.get("author"), str)
            or row.get("status") not in ("Unknown", "Error", "Warning", "Info")
            or type(row.get("creaTime")) is not int
        ):
            raise ValueError("Unexpected comment metadata or duplicate GUID.")
        seen.add(guid)
        row["guid"] = guid
    return sorted(rows, key=lambda r: r["guid"])


async def _comment_plan(client, entries, port, operation):
    port, target, _ = await write._context(client, port)
    available = {r["guid"]: r for r in await _rows(client, port)}
    before, items = {}, []
    for index, entry in enumerate(entries):
        if entry.issue_guid not in available:
            raise ValueError(f"Issue {entry.issue_guid} does not exist.")
        if entry.issue_guid not in before:
            before[entry.issue_guid] = await _comments(client, port, entry.issue_guid)
        parameters = {"issueId": {"guid": entry.issue_guid}, "text": entry.text}
        if entry.author is not None:
            parameters["author"] = entry.author
        items.append(
            {
                "index": index,
                "status": "ready",
                "issue_guid": entry.issue_guid,
                "issue": available[entry.issue_guid],
                "parameters": parameters,
            }
        )
    target["issue_comments"] = before
    return {"operation": operation, "target": target, "items": items}


async def _comment_dispatch(client, receipt):
    port, timeout = receipt["target"]["port"], receipt["write_timeout_seconds"]
    before = deepcopy(receipt["target"]["issue_comments"])
    receipt["undo_scope"] = "Each comment is one native command and Undo step."
    for index, item in enumerate(receipt["items"]):
        try:
            raw = await client.tapir(port, "AddCommentToIssue", item["parameters"], timeout=timeout)
        except (TapirError, CommandFailed) as exc:
            if isinstance(exc.detail, dict) and {"code", "message"} <= exc.detail.keys():
                item.update(status="failed", error=exc.detail)
                continue
            _unknown(receipt, index, exc)
            break
        except ArchicadError as exc:
            _unknown(receipt, index, exc)
            break
        item["write_response"] = raw
        if raw.get("success") is False and isinstance(raw.get("error"), dict):
            item.update(status="failed", error=raw["error"])
            continue
        if raw.get("success") is not True:
            _unknown(receipt, index, "Unexpected comment execution result.")
            break
        item["status"] = "unverified"
        try:
            rows = await _comments(client, port, item["issue_guid"], timeout)
        except (ArchicadError, ValueError) as exc:
            receipt["verification_error"] = str(exc)
            for later in receipt["items"][index + 1 :]:
                later.update(status="failed", not_attempted=True, error="Comment read-back failed.")
            break
        previous = {r["guid"]: r for r in before[item["issue_guid"]]}
        current = {r["guid"]: r for r in rows}
        added = [r for g, r in current.items() if g not in previous]
        item["after"] = added
        unchanged = all(current.get(g) == r for g, r in previous.items())
        expected = {
            "text": item["parameters"]["text"],
            "author": item["parameters"].get("author", "API"),
            "status": "Unknown",
        }
        matches = len(added) == 1 and all(added[0][k] == v for k, v in expected.items())
        ok = unchanged and matches
        item["status"] = "verified" if ok else "verification_failed"
        if ok:
            item["comment_guid"] = added[0]["guid"]
        else:
            item["mismatches"] = ["new_comment_or_existing_comments"]
        before[item["issue_guid"]] = rows


async def add_comment_to_issue(
    client: ArchicadClient,
    comments: list[dict | IssueComment],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/add 1–20 comments to existing issues; optional author defaults to API.

    Verifies a new GUID, text, author, Unknown status and unchanged prior comments.
    No deletions, attachments or project saving. Lost responses are never retried.
    """
    if not 1 <= len(comments) <= 20:
        raise ValueError("Pass between 1 and 20 comments.")
    entries = [
        c if isinstance(c, IssueComment) else IssueComment.model_validate(c) for c in comments
    ]
    return await write._write(
        client,
        entries,
        port,
        dry_run,
        confirmation_token,
        "add_comment_to_issue",
        planner_override=_comment_plan,
        dispatcher_override=_comment_dispatch,
    )


async def attach_elements_to_issue(
    client: ArchicadClient,
    issue_guid: str,
    element_guids: list[str],
    port: int | None = None,
    dry_run: bool = True,
    confirmation_token: str | None = None,
) -> dict:
    """Preview/attach 1–100 existing elements to one issue as Highlight only.

    This does not mark elements for Creation, Deletion or Modification. Existing
    Highlight links are kept. Explicit port and single-use token are required to apply.
    """
    if not 1 <= len(element_guids) <= MAX_ELEMENTS:
        raise ValueError(f"Pass between 1 and {MAX_ELEMENTS} elements.")
    entries = [_Attachment(issue_guid=issue_guid, element_guid=g) for g in element_guids]
    if len({e.element_guid for e in entries}) != len(entries):
        raise ValueError("Each element may appear only once per call.")
    return await write._write(
        client,
        entries,
        port,
        dry_run,
        confirmation_token,
        "attach_elements_to_issue",
        planner_override=_plan,
        dispatcher_override=_dispatch,
    )
