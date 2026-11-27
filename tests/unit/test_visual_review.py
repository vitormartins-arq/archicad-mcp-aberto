"""Synthetic PNGs and fake edits; these are NOT live/visually approved captures."""

import base64
import json
from types import SimpleNamespace

import pytest
from mcp.types import CallToolResult

from archicad_mcp_aberto import visual_mcp
from archicad_mcp_aberto.server import create_server
from archicad_mcp_aberto.tools import visual_review as review
from archicad_mcp_aberto.tools.window_capture import encode_png

WRITE = {"readOnlyHint": False, "destructiveHint": True}
READ = {"readOnlyHint": True}


def png(blank=False, width=128, height=128):
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            shade = 255 if blank or (x // 16 + y // 16) % 2 else 0
            pixels.extend((shade, shade, shade, 255))
    return encode_png(width, height, pixels)


def body(result):
    if isinstance(result, CallToolResult):
        return result.structuredContent or json.loads(result.content[0].text)
    if isinstance(result, tuple):
        return result[1]
    return json.loads(result[0].text)


@pytest.fixture
def fake(tmp_path, monkeypatch):
    mcp = visual_mcp.VisualReviewMCP("synthetic", visual_review_root=tmp_path)
    state = SimpleNamespace(
        stamp=1,
        writes=0,
        plan_calls=0,
        window_calls=0,
        blank=False,
        plan_error=False,
        window_error=False,
        fail_write=False,
        session="native-session",
        raise_identity=False,
    )
    client = SimpleNamespace(session_id="mcp-session")
    ctx = SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"client": client}))

    async def identity(c, port):
        if state.raise_identity:
            raise ValueError("No identity capability")
        return {
            "sessionId": state.session,
            "projectEpoch": "epoch",
            "projectPath": "test.pln",
            "modificationStamp": str(state.stamp),
            "untitled": False,
            "teamwork": False,
        }

    async def resolve(c, port):
        if port is None:
            raise ValueError("Multiple instances: explicit port required")
        return port

    async def plan(c, zoom=None, port=None):
        state.plan_calls += 1
        if state.plan_error:
            raise ValueError("Native capture not registered")
        return {
            "port": port,
            "zoom": zoom,
            "png_base64": base64.b64encode(png(state.blank)).decode(),
        }

    async def window(c, port=None):
        state.window_calls += 1
        if state.window_error:
            raise ValueError("Window is unavailable")
        return {"port": port, "title": "Synthetic fixture", "png": png(state.blank)}

    async def no_wait(_):
        return None

    monkeypatch.setattr(review, "_settle_pause", no_wait)
    monkeypatch.setattr(mcp.visual_reviews, "identity", identity)
    monkeypatch.setattr(visual_mcp, "resolve_port", resolve)
    monkeypatch.setattr(review.view_image, "capture_view_image", plan)
    monkeypatch.setattr(review.window_capture, "get_archicad_window_image", window)

    @mcp.tool(annotations=WRITE)
    async def change(
        ctx: visual_mcp.Context,
        values: list[str],
        port: int | None = None,
        dry_run: bool = True,
        confirmation_token: str | None = None,
    ) -> dict:
        if dry_run:
            return {"dry_run": True, "items": [{"value": v} for v in values]}
        state.writes += 1
        state.stamp += 1
        if state.fail_write:
            raise RuntimeError("Lost write response")
        return {
            "dry_run": False,
            "status": "verified",
            "items": [{"status": "verified", "value": v} for v in values],
        }

    @mcp.tool(annotations=WRITE)
    async def finish_model_task(ctx: visual_mcp.Context, port: int, dry_run: bool = False) -> dict:
        state.writes += 1
        return {"status": "verified"}

    @mcp.tool(annotations=READ)
    async def read_state(ctx: visual_mcp.Context, port: int) -> dict:
        return {"port": port, "actual": state.writes}

    async def call(name, **arguments):
        return await mcp._tool_manager.call_tool(name, arguments, context=ctx, convert_result=True)

    return SimpleNamespace(mcp=mcp, state=state, client=client, call=call, root=tmp_path)


async def apply(fake, values=None):
    return await fake.call(
        "change",
        values=values or ["one"],
        port=19723,
        dry_run=False,
        confirmation_token="toy-token",
    )


async def approve(fake, result, **overrides):
    payload = body(result)
    visual = payload["visual_review"]
    arguments = dict(
        review_ids=[visual["review_id"]],
        evidence_id=visual["evidence_ids"][-1],
        port=19723,
        outcome="passed",
        observation="Synthetic fixture covers the target.",
        context_correct=True,
        framing_sufficient=True,
        readable=True,
        full_coverage=True,
    )
    arguments.update(overrides)
    return await fake.call("review_visual_result", **arguments)


@pytest.mark.anyio
async def test_preview_and_reads_do_not_capture(fake):
    result = body(await fake.call("change", values=["one", "two"], port=19723))
    assert result["visual_review_plan"]["early_sample_required"]
    await fake.call("read_state", port=19723)
    assert fake.state.plan_calls == fake.state.window_calls == fake.state.writes == 0


@pytest.mark.anyio
async def test_numeric_success_returns_pending_with_inline_image(fake):
    result = await apply(fake)
    payload = body(result)
    assert payload["status"] == "awaiting_visual_review"
    assert payload["model_verification_status"] == "verified"
    assert not payload["task_complete"]
    assert any(c.type == "image" for c in result.content)
    with pytest.raises(Exception, match="incomplete"):
        await fake.call("finish_model_task", port=19723)
    assessed = body(await approve(fake, result))
    assert assessed["reviews"][0]["task_complete"]
    await fake.call("finish_model_task", port=19723)
    assert fake.state.writes == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    "flag", ["context_correct", "framing_sufficient", "readable", "full_coverage"]
)
async def test_wrong_context_crop_scale_or_missing_targets_cannot_pass(fake, flag):
    result = await apply(fake)
    with pytest.raises(Exception, match="cannot pass"):
        await approve(fake, result, **{flag: False})
    assert not body(result)["task_complete"]


@pytest.mark.anyio
async def test_native_failure_tries_real_window_alternative(fake):
    fake.state.plan_error = True
    result = await apply(fake)
    assert body(result)["visual_review"]["status"] == "awaiting_inspection"
    assert fake.state.plan_calls == fake.state.window_calls == 1
    assert any(c.type == "image" for c in result.content)


@pytest.mark.anyio
@pytest.mark.parametrize("problem", ["blank", "missing"])
async def test_no_acceptable_capture_remains_blocked(fake, problem):
    fake.state.blank = problem == "blank"
    fake.state.plan_error = fake.state.window_error = problem == "missing"
    result = await apply(fake)
    assert body(result)["visual_review"]["status"] == "blocked"
    assert fake.state.window_calls == 1
    assert not any(c.type == "image" for c in result.content)
    with pytest.raises(Exception, match="incomplete"):
        await fake.call("finish_model_task", port=19723)


@pytest.mark.anyio
async def test_batch_needs_early_sample_then_one_contextual_capture_covers_batch(fake):
    with pytest.raises(Exception, match="small sample"):
        await apply(fake, ["one", "two"])
    assert fake.state.writes == 0
    sample = await apply(fake)
    await approve(fake, sample)
    batch = await apply(fake, ["two", "three"])
    assert body(batch)["visual_review"]["early_sample_review_id"]
    await approve(fake, batch)
    assert fake.state.plan_calls == 2  # no image per element


@pytest.mark.anyio
async def test_changed_model_or_evidence_file_cannot_be_approved(fake):
    result = await apply(fake)
    fake.state.stamp += 1
    with pytest.raises(Exception, match="stale"):
        await approve(fake, result)
    review_id = body(result)["visual_review"]["review_id"]
    captured = await fake.call("capture_visual_review", review_ids=[review_id], port=19723)
    evidence_id = body(captured)["reviews"][0]["evidence_ids"][-1]
    record = fake.mcp.visual_reviews.records[review_id]
    from pathlib import Path

    Path(record["evidence"][-1]["path"]).write_bytes(b"altered")
    with pytest.raises(Exception, match="changed on disk"):
        await approve(fake, result, evidence_id=evidence_id)


@pytest.mark.anyio
async def test_corrections_require_recapture_and_new_assessment(fake):
    result = await apply(fake)
    await approve(
        fake,
        result,
        outcome="needs_correction",
        observation="Synthetic target overlap needs correction.",
    )
    correction = await apply(fake)
    first = body(result)["visual_review"]["review_id"]
    second = body(correction)["visual_review"]["review_id"]
    capture = body(await fake.call("capture_visual_review", review_ids=[first, second], port=19723))
    evidence = capture["reviews"][0]["evidence_ids"][-1]
    await fake.call(
        "review_visual_result",
        review_ids=[first, second],
        evidence_id=evidence,
        port=19723,
        outcome="passed",
        observation="Correction now covers both targets.",
        context_correct=True,
        framing_sufficient=True,
        readable=True,
        full_coverage=True,
    )
    await fake.call("finish_model_task", port=19723)


@pytest.mark.anyio
async def test_unknown_write_is_not_retried_and_needs_readback_plus_image(fake):
    fake.state.fail_write = True
    result = await apply(fake)
    assert result.isError and fake.state.writes == 1
    with pytest.raises(Exception, match="readback"):
        await approve(fake, result)
    review_id = body(result)["visual_review"]["review_id"]
    readback = body(
        await fake.call(
            "reconcile_visual_review",
            review_id=review_id,
            read_tool="read_state",
            arguments={},
            port=19723,
        )
    )
    assert readback["readback"]["actual"] == 1 and not readback["task_complete"]
    await approve(
        fake, result, reconciliation_observation="Current readback confirms one applied edit."
    )
    assert fake.state.writes == 1


@pytest.mark.anyio
async def test_reconciliation_refuses_mutating_tool(fake):
    result = await apply(fake)
    with pytest.raises(Exception, match="read-only"):
        await fake.call(
            "reconcile_visual_review",
            review_id=body(result)["visual_review"]["review_id"],
            read_tool="change",
            arguments={},
            port=19723,
        )


@pytest.mark.anyio
async def test_ambiguous_target_and_disk_failure_do_not_write(fake, monkeypatch):
    with pytest.raises(Exception, match="Multiple instances"):
        await fake.call("change", values=["one"], dry_run=False)

    def fail(record):
        raise OSError("disk full")

    monkeypatch.setattr(fake.mcp.visual_reviews, "save", fail)
    with pytest.raises(Exception, match="disk full"):
        await apply(fake)
    assert fake.state.writes == 0


@pytest.mark.anyio
async def test_all_public_writes_are_guarded_and_late_private_registration_inherits(fake):
    mcp = create_server()
    writes = [
        t for t in mcp._tool_manager.list_tools() if t.annotations and t.annotations.destructiveHint
    ]
    assert len(writes) > 100
    assert all(getattr(t.fn, "_visual_guarded", False) for t in writes)
    report = body(await fake.call("visual_review_coverage"))
    assert report["all_guarded"]
    assert {"change", "finish_model_task"} <= {r["tool"] for r in report["writes"]}


@pytest.mark.anyio
async def test_pending_review_survives_restart_and_requires_recapture(fake, monkeypatch):
    result = await apply(fake)
    restarted = review.VisualReviews(fake.root)
    review_id = body(result)["visual_review"]["review_id"]
    assert review_id in restarted.records
    assert restarted.records[review_id]["status"] == "awaiting_inspection"
    fake.client.session_id = "new-mcp-session"
    with pytest.raises(ValueError, match="Old MCP session"):
        restarted.get(review_id, fake.client, 19723)


@pytest.mark.parametrize("data", [b"not a PNG", png(True), png(width=40), png()[:-12]])
def test_invalid_empty_tiny_or_truncated_png_is_refused(data):
    with pytest.raises((ValueError, struct_error())):
        review.inspect_png(data)


def struct_error():
    import struct

    return struct.error


def test_real_pixel_content_is_decoded_not_just_png_magic():
    metrics = review.inspect_png(png())
    assert metrics["width"] == metrics["height"] == 128
    assert len(metrics["sha256"]) == 64


def test_preview_sample_size_is_bound_to_exact_token_not_latest_preview(tmp_path):
    manager = review.VisualReviews(tmp_path)
    manager.remember_preview("change", 19723, {}, {"confirmation_token": "sample", "items": [{}]})
    manager.remember_preview(
        "change", 19723, {}, {"confirmation_token": "batch", "items": [{}, {}]}
    )
    assert manager.preview_count("change", 19723, {"confirmation_token": "sample"}) == 1
    assert manager.preview_count("change", 19723, {"confirmation_token": "batch"}) == 2


@pytest.mark.anyio
async def test_element_framing_uses_real_boxes_with_context_margin_without_window_zoom(
    fake, monkeypatch
):
    result = await apply(fake)
    seen = []

    async def boxes(client, guids, port, mode):
        assert port == 19723 and mode == "2d"
        return {
            "boundingBoxes": [
                {"guid": guids[0], "box": {"xMin": 10, "yMin": 20, "xMax": 11, "yMax": 21}}
            ]
        }

    async def capture(client, zoom=None, port=None):
        seen.append(zoom)
        return {"port": port, "zoom": zoom, "png_base64": base64.b64encode(png()).decode()}

    monkeypatch.setattr(review.read, "get_bounding_boxes", boxes)
    monkeypatch.setattr(review.view_image, "capture_view_image", capture)
    await fake.call(
        "capture_visual_review",
        review_ids=[body(result)["visual_review"]["review_id"]],
        port=19723,
        element_guids=["one"],
        source="plan",
    )
    assert seen == [{"xMin": 9.5, "yMin": 19.5, "xMax": 11.5, "yMax": 21.5}]


@pytest.mark.anyio
async def test_unavailable_target_bounds_cannot_claim_full_framing(fake, monkeypatch):
    async def boxes(client, guids, port, mode):
        return {"boundingBoxes": [{"guid": "one", "error": "not found"}]}

    monkeypatch.setattr(review.read, "get_bounding_boxes", boxes)
    with pytest.raises(ValueError, match="unavailable"):
        await review.element_zoom(fake.client, 19723, ["one"])


@pytest.mark.anyio
async def test_missing_identity_can_return_image_but_cannot_complete(fake):
    fake.state.raise_identity = True
    result = await apply(fake)
    assert fake.state.writes == 1
    assert body(result)["visual_review"]["status"] == "blocked"
    assert any(c.type == "image" for c in result.content)
    with pytest.raises(Exception, match="identity"):
        await approve(fake, result)


@pytest.mark.anyio
async def test_native_3d_capture_is_available_without_changing_camera(fake, monkeypatch):
    result = await apply(fake)

    async def addon(client, port, name, parameters=None):
        assert name == "Get3DWindowImage" and parameters == {"format": "png"}
        return {"image": base64.b64encode(png()).decode()}

    monkeypatch.setattr(review.scenes, "_addon", addon)
    capture = await fake.call(
        "capture_visual_review",
        review_ids=[body(result)["visual_review"]["review_id"]],
        port=19723,
        source="3d",
    )
    assert any(c.type == "image" for c in capture.content)


@pytest.mark.anyio
async def test_visual_review_uses_real_resolver_with_two_simulated_instances(tmp_path):
    from archicad_mcp_aberto.connection import ArchicadClient
    from tests.unit.fake_archicad import FakeArchicad, fake_transport

    first, second = FakeArchicad(19723), FakeArchicad(19724)
    async with ArchicadClient(
        ports=[19723, 19724], transport=fake_transport(first, second)
    ) as client:
        mcp = visual_mcp.VisualReviewMCP("ambiguous", visual_review_root=tmp_path)
        ctx = SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"client": client}))
        with pytest.raises(Exception, match="port"):
            await mcp._tool_manager.call_tool("get_visual_reviews", {}, context=ctx)


@pytest.mark.anyio
async def test_discard_changed_export_then_capture_stable_window_with_fresh_context(
    fake, monkeypatch
):
    async def changed_plan(client, zoom=None, port=None):
        fake.state.stamp += 1
        return {"png_base64": base64.b64encode(png()).decode(), "port": port}

    monkeypatch.setattr(review.view_image, "capture_view_image", changed_plan)
    result = await apply(fake)
    record = fake.mcp.visual_reviews.records[body(result)["visual_review"]["review_id"]]
    assert record["capture_attempts"][0]["status"] == "failed"
    assert record["capture_attempts"][0]["changed_context_fields"] == ["modificationStamp"]
    assert record["capture_attempts"][1]["status"] == "captured"
    assert len(record["evidence"]) == 1
    assert record["evidence"][0]["source"] == "window"
    assert record["evidence"][0]["context"]["modificationStamp"] == str(fake.state.stamp)
    assert record["task_complete"] is False  # Capturing never constitutes approval.
    await approve(fake, result)


@pytest.mark.anyio
async def test_every_source_changing_during_its_own_capture_remains_blocked(fake, monkeypatch):
    async def changed_plan(client, zoom=None, port=None):
        fake.state.stamp += 1
        return {"png_base64": base64.b64encode(png()).decode()}

    async def changed_window(client, port=None):
        fake.state.stamp += 1
        return {"png": png()}

    async def changed_3d(*args, **kwargs):
        fake.state.stamp += 1
        return {"image": base64.b64encode(png()).decode()}

    monkeypatch.setattr(review.view_image, "capture_view_image", changed_plan)
    monkeypatch.setattr(review.window_capture, "get_archicad_window_image", changed_window)
    monkeypatch.setattr(review.scenes, "_addon", changed_3d)
    result = await apply(fake)
    record = fake.mcp.visual_reviews.records[body(result)["visual_review"]["review_id"]]
    assert record["status"] == "blocked"
    assert not record["evidence"]
    assert len(record["capture_attempts"]) == 3
    assert all(
        a["changed_context_fields"] == ["modificationStamp"] for a in record["capture_attempts"]
    )
    assert not any(c.type == "image" for c in result.content)


@pytest.mark.anyio
async def test_project_switch_during_export_cannot_be_rebased_for_fallback(fake, monkeypatch):
    async def changed_plan(client, zoom=None, port=None):
        fake.state.session = "different-project-session"
        return {"png_base64": base64.b64encode(png()).decode()}

    monkeypatch.setattr(review.view_image, "capture_view_image", changed_plan)
    result = await apply(fake)
    record = fake.mcp.visual_reviews.records[body(result)["visual_review"]["review_id"]]
    assert record["status"] == "blocked"
    assert not record["evidence"]
    assert fake.state.window_calls == 0


@pytest.mark.anyio
async def test_nonsettling_context_refuses_capture_before_dispatch(fake, monkeypatch):
    original_identity = fake.mcp.visual_reviews.identity

    async def moving_identity(client, port):
        fake.state.stamp += 1
        return await original_identity(client, port)

    monkeypatch.setattr(fake.mcp.visual_reviews, "identity", moving_identity)
    result = await apply(fake)
    record = fake.mcp.visual_reviews.records[body(result)["visual_review"]["review_id"]]
    assert record["status"] == "blocked"
    assert not record["evidence"]
    assert fake.state.plan_calls == fake.state.window_calls == 0


async def supersession_pair(fake):
    old = await apply(fake)
    await approve(fake, old, outcome="needs_correction")
    final = await apply(fake)
    old_id = body(old)["visual_review"]["review_id"]
    final_id = body(final)["visual_review"]["review_id"]
    await fake.call(
        "reconcile_visual_review",
        review_id=old_id,
        read_tool="read_state",
        arguments={},
        port=19723,
    )
    await approve(fake, final)
    return old_id, final_id


async def supersede(fake, old_id, final_id):
    return await fake.call(
        "supersede_visual_reviews",
        review_ids=[old_id],
        replacement_review_id=final_id,
        port=19723,
        observation=(
            "Final correction replaces the old position; readback and image cover all targets."
        ),
    )


@pytest.mark.anyio
async def test_supersession_preserves_failed_history_and_allows_final_save(fake):
    old_id, final_id = await supersession_pair(fake)
    original = json.loads((fake.root / f"{old_id}.json").read_text())
    with pytest.raises(Exception, match="incomplete"):
        await fake.call("finish_model_task", port=19723)
    result = body(await supersede(fake, old_id, final_id))
    record = fake.mcp.visual_reviews.records[old_id]
    assert result["reviews"][0]["status"] == "superseded"
    assert record["task_complete"] is False
    assert record["assessment"] == original["assessment"]
    assert record["model_receipt"] == original["model_receipt"]
    assert record["evidence"] == original["evidence"]
    assert record["supersession"]["previous_status"] == "needs_correction"
    await fake.call("finish_model_task", port=19723)
    restored = review.VisualReviews(fake.root)
    assert restored.resolved(restored.records[old_id])
    assert fake.mcp.visual_reviews.sample("change", record["context"]) != old_id
    with pytest.raises(Exception, match="historical"):
        await fake.call("capture_visual_review", review_ids=[old_id], port=19723)
    with pytest.raises(Exception, match="cannot be approved"):
        await fake.call(
            "review_visual_result",
            review_ids=[old_id],
            port=19723,
            evidence_id=record["evidence"][-1]["evidence_id"],
            outcome="passed",
            observation="Attempt to approve an obsolete incorrect configuration.",
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "fault",
    [
        "unpassed",
        "stale",
        "tampered",
        "missing_readback",
        "other_project",
        "other_scope",
        "other_client",
        "self",
        "already_passed",
    ],
)
async def test_supersession_refuses_missing_or_invalid_final_evidence(fake, fault):
    old_id, final_id = await supersession_pair(fake)
    records = fake.mcp.visual_reviews.records
    old, final = records[old_id], records[final_id]
    if fault == "unpassed":
        final["status"] = "needs_correction"
    if fault == "stale":
        fake.state.stamp += 1
    if fault == "tampered":
        from pathlib import Path

        Path(final["evidence"][-1]["path"]).write_bytes(b"changed")
    if fault == "missing_readback":
        old.pop("numeric_reconciliation")
    if fault == "other_project":
        old["context"]["sessionId"] = "another"
    if fault == "other_scope":
        old["required_representation"] = "layout"
    if fault == "other_client":
        old["client_session"] = "another"
    if fault == "self":
        final_id = old_id
    if fault == "already_passed":
        old["status"] = "passed"
    with pytest.raises(Exception, match="review|Replacement|Choose|session"):
        await supersede(fake, old_id, final_id)
    assert "supersession" not in old


@pytest.mark.anyio
async def test_reopened_replacement_blocks_dependent_superseded_reviews(fake):
    old_id, final_id = await supersession_pair(fake)
    await supersede(fake, old_id, final_id)
    await fake.call("capture_visual_review", review_ids=[final_id], port=19723)
    assert not fake.mcp.visual_reviews.resolved(fake.mcp.visual_reviews.records[old_id])
    with pytest.raises(Exception, match="incomplete"):
        await fake.call("finish_model_task", port=19723)


@pytest.mark.anyio
async def test_supersession_requires_explicit_port_with_two_simulated_instances(tmp_path):
    from archicad_mcp_aberto.connection import ArchicadClient
    from tests.unit.fake_archicad import FakeArchicad, fake_transport

    first, second = FakeArchicad(19723), FakeArchicad(19724)
    async with ArchicadClient(
        ports=[19723, 19724], transport=fake_transport(first, second)
    ) as client:
        mcp = visual_mcp.VisualReviewMCP("ambiguous", visual_review_root=tmp_path)
        ctx = SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"client": client}))
        with pytest.raises(Exception, match="port"):
            await mcp._tool_manager.call_tool(
                "supersede_visual_reviews",
                {
                    "review_ids": ["obsolete"],
                    "replacement_review_id": "final",
                    "observation": (
                        "The final correction covers all obsolete targets and side effects."
                    ),
                },
                context=ctx,
            )
