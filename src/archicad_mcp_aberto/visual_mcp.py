"""Central MCP-boundary visual completion guard, inherited by private extensions.

Tool logic and its numeric receipts remain unchanged for Python API consumers.
Every destructiveHint tool registered through add_tool is wrapped, including tools
added after create_server returns. No per-tool opt-in can silently omit new writes.
"""

from __future__ import annotations

import inspect
import json
from functools import wraps
from typing import Literal

from mcp.server.fastmcp import Context, FastMCP
from mcp.types import CallToolResult, TextContent

from archicad_mcp_aberto.connection import resolve_port
from archicad_mcp_aberto.tools.visual_review import (
    CHECKPOINT_TOOLS,
    SAVE_TOOLS,
    VisualReviews,
    item_count,
    preview_result,
)

READ = {"readOnlyHint": True, "openWorldHint": False}


class VisualReviewMCP(FastMCP):
    def __init__(self, *args, visual_review_root=None, **kwargs):
        self.visual_reviews = VisualReviews(visual_review_root)
        super().__init__(*args, **kwargs)

        @self.tool(annotations=READ)
        async def get_visual_reviews(ctx: Context, port: int | None = None) -> dict:
            """List visual completion records for this project. Pure read; no capture.

            A numeric/API success is not completion. Pending/blocked records prevent
            final saving through this server. No computer-use automation is performed.
            """
            client = ctx.request_context.lifespan_context["client"]
            chosen = await resolve_port(client, port)
            current = await self.visual_reviews.identity(client, chosen)
            from archicad_mcp_aberto.tools.visual_review import same_project

            return {
                "port": chosen,
                "reviews": [
                    self.visual_reviews.summary(r)
                    for r in self.visual_reviews.records.values()
                    if r.get("port") == chosen
                    and (not r.get("context") or same_project(r["context"], current))
                ],
            }

        @self.tool(annotations=READ)
        async def capture_visual_review(
            ctx: Context,
            review_ids: list[str],
            port: int,
            source: Literal["auto", "plan", "window", "3d"] = "auto",
            zoom: dict[str, float] | None = None,
            element_guids: list[str] | None = None,
        ) -> CallToolResult:
            """Capture actual post-edit evidence for 1-50 reviews on an explicit port.

            auto tries native 2D then the existing window capture capability. For 3D
            select 3d explicitly. zoom uses model metres and is restored by native 2D
            capture. Use existing MCP navigation/zoom to show the affected target first.
            Label evidence must show object, face, direction and nearby annotations.
            Data changes need the actual schedule/dialog/documentation, not a floor plan.
            Empty/corrupt/tiny images are refused. You must still LOOK at the image,
            reject wrong/cropped context and assess the result with review_visual_result.
            Several reviews may share one contextual image; capture more for omitted areas.
            element_guids frames their real 2D boxes with a neighbourhood margin directly
            in native capture, without WindowZoom/SetZoom. Do not mix this with zoom;
            activate the correct story/window first and split floors/areas as needed.
            """
            client = ctx.request_context.lifespan_context["client"]
            chosen = await resolve_port(client, port)
            async with self.visual_reviews.lock:
                if element_guids is not None:
                    if zoom is not None or source == "3d":
                        raise ValueError("Use either explicit zoom or 2D element framing.")
                    from archicad_mcp_aberto.tools.visual_review import element_zoom

                    zoom = await element_zoom(client, chosen, element_guids)
                return await self.visual_reviews.capture(client, review_ids, chosen, zoom, source)

        @self.tool(annotations=READ)
        async def reconcile_visual_review(
            ctx: Context,
            review_id: str,
            read_tool: str,
            arguments: dict,
            port: int,
        ) -> dict:
            """Read current numeric state to reconcile a failed/unknown write; never retry it.

            Choose an existing read-only BIM getter appropriate to the changed data.
            The actual readback is returned and recorded. Inspect/compare it with the
            intended result, then capture correct-context images and pass a concrete
            reconciliation_observation to review_visual_result. Neither readback nor
            this record certifies the intended result without your assessment.
            """
            client = ctx.request_context.lifespan_context["client"]
            chosen = await resolve_port(client, port)
            candidate = self._tool_manager.get_tool(read_tool)
            if (
                not candidate
                or not candidate.annotations
                or candidate.annotations.readOnlyHint is not True
                or "visual_review" in read_tool
                or read_tool == "review_visual_result"
            ):
                raise ValueError("Choose a registered read-only BIM getter.")
            if "port" not in candidate.parameters.get("properties", {}):
                raise ValueError("Readback getter must support an explicit port.")
            if arguments.get("port", chosen) != chosen:
                raise ValueError("Readback port differs from the reviewed project.")
            async with self.visual_reviews.lock:
                record = self.visual_reviews.get(review_id, client, chosen)
                before = await self.visual_reviews.identity(client, chosen)
                from archicad_mcp_aberto.tools.visual_review import same_project

                if record.get("context") and not same_project(record["context"], before):
                    raise ValueError("Project identity changed.")
                result = await self._tool_manager.call_tool(
                    read_tool,
                    {**arguments, "port": chosen},
                    context=ctx,
                )
                after = await self.visual_reviews.identity(client, chosen)
                if before != after:
                    raise ValueError("Project changed during reconciliation readback.")
                if isinstance(result, CallToolResult) and result.isError:
                    raise ValueError("Readback failed; outcome remains unknown.")
                record["numeric_reconciliation"] = {
                    "read_tool": read_tool,
                    "arguments": {**arguments, "port": chosen},
                    "result": result,
                    "context": after,
                }
                self.visual_reviews.save(record)
                return {
                    "review_id": review_id,
                    "readback": result,
                    "task_complete": False,
                    "instruction": "Compare this actual readback with the intended outcome. "
                    "Then inspect images; do not repeat the original write.",
                }

        @self.tool(annotations=READ)
        async def review_visual_result(
            ctx: Context,
            review_ids: list[str],
            evidence_id: str,
            port: int,
            outcome: Literal["passed", "needs_correction", "blocked"],
            observation: str,
            context_correct: bool = False,
            framing_sufficient: bool = False,
            readable: bool = False,
            full_coverage: bool = False,
            reconciliation_observation: str | None = None,
        ) -> dict:
            """Record your assessment ONLY AFTER looking at the actual returned image.

            State concretely what is visible, alignment/overlaps, scale and scope.
            For labels check object/face/reading direction/neighbourhood. For layouts
            inspect updated drawings/full sheet; use real PDF/window evidence as needed.
            A capture is not approval. Unknown writes need reconciliation, not retries.
            If anything is wrong, mark needs_correction, correct, recapture and assess.
            If no suitable image is available, report blocked and the task INCOMPLETE.
            The server records your assessment; it does not run a vision model.
            """
            client = ctx.request_context.lifespan_context["client"]
            chosen = await resolve_port(client, port)
            async with self.visual_reviews.lock:
                return await self.visual_reviews.assess(
                    client,
                    review_ids,
                    evidence_id,
                    chosen,
                    outcome,
                    observation,
                    context_correct,
                    framing_sufficient,
                    readable,
                    full_coverage,
                    reconciliation_observation,
                )

        @self.tool(annotations=READ)
        async def visual_review_coverage() -> dict:
            """Audit coverage of every currently registered project/model write tool.

            Includes private tools registered after the public server was constructed.
            View-only actions/reads are excluded; checkpoint and final-save policies
            are explicit. This only inspects the server registry, never Archicad.
            """
            rows = []
            for tool in self._tool_manager.list_tools():
                if tool.annotations and tool.annotations.destructiveHint:
                    policy = (
                        "checkpoint"
                        if tool.name in CHECKPOINT_TOOLS
                        else "completion_gate"
                        if tool.name in SAVE_TOOLS
                        else "preview_only"
                        if (tool.meta or {}).get("visual_review", {}).get("policy")
                        == "preview_only"
                        else "image_review"
                    )
                    rows.append(
                        {
                            "tool": tool.name,
                            "policy": policy,
                            "guarded": bool(getattr(tool.fn, "_visual_guarded", False)),
                        }
                    )
            return {"writes": rows, "all_guarded": all(row["guarded"] for row in rows)}

    def add_tool(self, fn, *args, **kwargs):
        super().add_tool(fn, *args, **kwargs)
        name = kwargs.get("name") or fn.__name__
        tool = self._tool_manager.get_tool(name)
        if (
            not tool
            or not tool.annotations
            or not tool.annotations.destructiveHint
            or getattr(tool.fn, "_visual_guarded", False)
        ):
            return
        original = tool.fn
        signature = inspect.signature(original)
        policy = (tool.meta or {}).get("visual_review", {})

        @wraps(original)
        async def guarded(**arguments):
            bound = signature.bind(**arguments)
            bound.apply_defaults()
            values = dict(bound.arguments)
            ctx = values.get("ctx")
            client = ctx.request_context.lifespan_context["client"]
            port = await resolve_port(client, values.get("port"))
            async with self.visual_reviews.lock:
                if name in SAVE_TOOLS:
                    await self.visual_reviews.assert_complete(client, port)
                    return await original(**arguments)
                if name in CHECKPOINT_TOOLS:
                    return await original(**arguments)
                if policy.get("policy") == "preview_only":
                    result = await original(**arguments)
                    if isinstance(result, dict) and policy.get("apply_tool"):
                        self.visual_reviews.remember_preview(
                            policy["apply_tool"],
                            port,
                            values,
                            result,
                        )
                    return result
                # Internal orchestrators without dry_run preview with no confirmation map.
                is_preview = values.get("dry_run") is True or (
                    "confirmation_tokens" in values and not values["confirmation_tokens"]
                )
                if is_preview:
                    result = await original(**arguments)
                    if isinstance(result, dict):
                        count = self.visual_reviews.remember_preview(name, port, values, result)
                        return {
                            **result,
                            "visual_review_plan": {
                                "early_sample_required": count > 1,
                                "item_count": count,
                                "instruction": "First apply and visually inspect a small "
                                "sample of this operation, then preview/apply the rest. "
                                "Final images must cover all changed areas at readable scale.",
                            },
                        }
                    return result
                count = self.visual_reviews.preview_count(name, port, values)
                try:
                    context = await self.visual_reviews.identity(client, port)
                except Exception:
                    context = None
                if count > 1 and (not context or not self.visual_reviews.sample(name, context)):
                    raise ValueError(
                        "Before applying this batch, apply a small sample of this "
                        "operation and inspect its image. No batch write dispatched."
                    )
                record = await self.visual_reviews.start(client, name, values, port, count)
                error = None
                try:
                    result = await original(**arguments)
                    if preview_result(values, result):
                        record.update(status="preview_only", task_complete=True)
                        self.visual_reviews.save(record)
                        return result
                    record["model_outcome"] = (
                        result.get("status", "reported") if isinstance(result, dict) else "reported"
                    )
                    record["model_receipt"] = result
                    record["item_count"] = max(record["item_count"], item_count(values, result))
                except Exception as exc:
                    error = str(exc)
                    result = {"status": "unknown", "error": error}
                    record.update(model_outcome="unknown", error=error)
                record.update(status="awaiting_capture", task_complete=False)
                self.visual_reviews.save(record)
                capture = None
                try:
                    capture = await self.visual_reviews.capture(client, [record["review_id"]], port)
                except Exception as exc:
                    record.update(status="blocked", blocker=str(exc), task_complete=False)
                    self.visual_reviews.save(record)
                summary = self.visual_reviews.summary(record)
                if isinstance(result, dict):
                    payload = {
                        **result,
                        "model_verification_status": result.get("status"),
                        "task_complete": False,
                        "visual_review": summary,
                    }
                    if result.get("status") == "verified":
                        payload["status"] = "awaiting_visual_review"
                else:
                    payload = {
                        "model_result": result,
                        "task_complete": False,
                        "visual_review": summary,
                    }
                content = [TextContent(type="text", text=json.dumps(payload, default=str))]
                if capture:
                    content.extend(c for c in capture.content if c.type == "image")
                return CallToolResult(
                    content=content, structuredContent=payload, isError=bool(error)
                )

        guarded._visual_guarded = True
        tool.fn = guarded
