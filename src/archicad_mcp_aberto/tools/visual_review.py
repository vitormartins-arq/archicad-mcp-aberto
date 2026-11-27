"""Image-backed completion ledger. Numeric verification is never visual approval.

Captures are candidates until the assistant actually inspects them and records a
context/framing/readability/coverage assessment. No vision model runs in this server.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import struct
import zlib
from pathlib import Path
from uuid import uuid4

from mcp.types import CallToolResult, ImageContent, TextContent

from archicad_mcp_aberto.tools import project_save, read, scenes, view_image, window_capture

IDENTITY = ("sessionId", "projectEpoch", "projectPath")
SAVE_TOOLS = {"finish_model_task", "save_project_as", "save_next_project_revision"}
CHECKPOINT_TOOLS = {"begin_model_task"}
_settle_pause = asyncio.sleep


def inspect_png(data: bytes) -> dict:
    """Bounded decoding of 8-bit RGB/RGBA PNG; rejects corrupt, tiny or blank captures."""
    if len(data) > 12 * 1024 * 1024 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Capture is not a bounded PNG.")
    offset, payload, header = 8, bytearray(), None
    ended = False
    while offset + 12 <= len(data):
        size = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        chunk = data[offset + 8 : offset + 8 + size]
        end = offset + 12 + size
        if end > len(data):
            raise ValueError("Truncated PNG.")
        crc = struct.unpack(">I", data[end - 4 : end])[0]
        if zlib.crc32(kind + chunk) & 0xFFFFFFFF != crc:
            raise ValueError("Invalid PNG checksum.")
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", chunk)
        elif kind == b"IDAT":
            payload.extend(chunk)
        elif kind == b"IEND":
            ended = True
            break
        offset = end
    if not header or not ended:
        raise ValueError("Incomplete PNG.")
    width, height, depth, color, compression, filtering, interlace = header
    if min(width, height) < 128 or width * height > 16_000_000:
        raise ValueError("Capture is too small or too large to review.")
    if depth != 8 or color not in (2, 6) or compression or filtering or interlace:
        raise ValueError("Unsupported PNG encoding; try another capture capability.")
    channels = 3 if color == 2 else 4
    stride = width * channels
    expected = (stride + 1) * height
    decoder = zlib.decompressobj()
    raw = decoder.decompress(payload, expected + 1)
    if len(raw) != expected or not decoder.eof:
        raise ValueError("Invalid PNG pixel length.")
    previous = bytearray(stride)
    colors, contrast = set(), [255, 0]
    for y in range(height):
        start = y * (stride + 1)
        mode = raw[start]
        if mode not in range(5):
            raise ValueError("Invalid PNG row filter.")
        if len(colors) >= 2 and contrast[1] - contrast[0] >= 12:
            continue  # Nonuniform content established; semantic review remains mandatory.
        row = bytearray(raw[start + 1 : start + 1 + stride])
        for x in range(stride) if mode else ():
            a = row[x - channels] if x >= channels else 0
            b = previous[x]
            c = previous[x - channels] if x >= channels else 0
            if mode == 1:
                predictor = a
            elif mode == 2:
                predictor = b
            elif mode == 3:
                predictor = (a + b) // 2
            elif mode == 4:
                p = a + b - c
                distances = (abs(p - a), abs(p - b), abs(p - c))
                predictor = (a, b, c)[distances.index(min(distances))]
            else:
                predictor = 0
            row[x] = (row[x] + predictor) & 255
        # Inspect all pixels; transparent noise is not visible content.
        for x in range(0, stride, channels):
            rgb = tuple(row[x : x + 3])
            if channels == 4:
                alpha = row[x + 3]
                rgb = tuple((v * alpha + 255 * (255 - alpha)) // 255 for v in rgb)
            if len(colors) < 16:
                colors.add(rgb)
            contrast[0] = min(contrast[0], min(rgb))
            contrast[1] = max(contrast[1], max(rgb))
        previous = row
    if len(colors) < 2 or contrast[1] - contrast[0] < 12:
        raise ValueError("Capture is blank or has insufficient contrast.")
    return {"width": width, "height": height, "sha256": hashlib.sha256(data).hexdigest()}


def same_project(a: dict, b: dict) -> bool:
    return bool(a and b) and all(k in a and k in b and a[k] == b[k] for k in IDENTITY)


def scope_for(name: str) -> str:
    if any(word in name for word in ("label", "dimension", "text", "line", "fill", "hotspot")):
        return "model_2d"
    if any(word in name for word in ("layout", "drawing", "publish")):
        return "layout"
    if any(
        word in name
        for word in (
            "property",
            "classification",
            "info",
            "attribute",
            "layer",
            "favorite",
            "resource",
            "library",
            "obj_batch",
        )
    ):
        return "data_or_documentation"
    if any(word in name for word in ("view", "folder", "navigator", "story", "stories")):
        return "navigator_and_saved_view"
    return "model_2d_or_3d"


def preview_result(arguments: dict, result) -> bool:
    if isinstance(result, dict) and result.get("dry_run") is True:
        return True
    if arguments.get("dry_run") is True:
        return True
    if "confirmation_tokens" in arguments and not arguments["confirmation_tokens"]:
        return True
    return False


def item_count(arguments: dict, result) -> int:
    if isinstance(result, dict) and isinstance(result.get("items"), list):
        return max(1, len(result["items"]))
    if isinstance(result, dict) and isinstance(result.get("calls"), list):
        return max(1, sum(c.get("count", 1) for c in result["calls"] if isinstance(c, dict)))
    if isinstance(result, dict) and isinstance(result.get("files"), list):
        return max(1, len(result["files"]))
    lists = [
        len(v) for k, v in arguments.items() if isinstance(v, list) and k not in {"fields", "kinds"}
    ]
    return max([1, *lists])


async def element_zoom(client, port: int, element_guids: list[str]) -> dict:
    """Read real 2D bounds with neighbourhood margin, without changing the live zoom."""
    if not 1 <= len(element_guids) <= 100:
        raise ValueError("Frame 1 to 100 elements; split floors/areas into contextual captures.")
    result = await read.get_bounding_boxes(client, element_guids, port, "2d")
    rows = result["boundingBoxes"]
    if len(rows) != len(element_guids) or any("box" not in row for row in rows):
        raise ValueError("Some target bounds are unavailable; do not claim full visual coverage.")
    boxes = [row["box"] for row in rows]
    if any(not math.isfinite(float(b[k])) for b in boxes for k in ("xMin", "yMin", "xMax", "yMax")):
        raise ValueError("Non-finite target bounds.")
    x0, y0 = min(b["xMin"] for b in boxes), min(b["yMin"] for b in boxes)
    x1, y1 = max(b["xMax"] for b in boxes), max(b["yMax"] for b in boxes)
    margin = max(0.5, max(x1 - x0, y1 - y0) * 0.15)
    return {"xMin": x0 - margin, "yMin": y0 - margin, "xMax": x1 + margin, "yMax": y1 + margin}


class VisualReviews:
    def __init__(self, root: Path | None = None):
        self.root = root or Path.home() / ".archicad-mcp-aberto" / "visual-reviews"
        self.records: dict[str, dict] = {}
        self.lock = asyncio.Lock()
        self.previews: dict[tuple[str, int, str], int] = {}
        if self.root.exists():
            for path in self.root.glob("*.json"):
                try:
                    record = json.loads(path.read_text(encoding="utf-8"))
                    if record.get("review_id"):
                        self.records[record["review_id"]] = record
                except (OSError, ValueError):
                    # Unreadable pending receipts cannot be silently forgotten.
                    self.records[f"corrupt:{path.name}"] = {
                        "status": "blocked",
                        "review_id": f"corrupt:{path.name}",
                        "blocker": "Unreadable visual review receipt; inspect it locally.",
                    }

    def save(self, record: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.root / f"{record['review_id']}.json"
        temporary = path.with_suffix(".json.pending")
        temporary.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        temporary.replace(path)

    def remember_preview(self, tool: str, port: int, arguments: dict, result: dict) -> int:
        count = item_count(arguments, result)
        token = result.get("confirmation_token") or result.get("confirmation")
        if isinstance(token, str):
            self.previews[tool, port, token] = count
        for call in result.get("calls", []):
            token = call.get("confirmation_token") if isinstance(call, dict) else None
            if isinstance(token, str):
                self.previews[tool, port, token] = call.get("count", 1)
        if len(self.previews) > 4096:
            self.previews.pop(next(iter(self.previews)))
        return count

    def preview_count(self, tool: str, port: int, arguments: dict) -> int:
        tokens = list((arguments.get("confirmation_tokens") or {}).values())
        token = arguments.get("confirmation_token") or arguments.get("confirmation")
        if token:
            tokens.append(token)
        count = sum(self.previews.get((tool, port, token), 0) for token in tokens)
        return max(item_count(arguments, None), count)

    async def identity(self, client, port: int) -> dict:
        return await project_save._context(client, port)

    async def capture_context(self, client, port: int) -> dict:
        """Exact bounded stabilization before a capture; never waive model stamps.

        A discarded native export can cause deferred updates. Each fallback starts
        a new observation interval after those updates settle, instead of reusing
        the context from before the failed export. Project identity must never change.
        """
        first = previous = await self.identity(client, port)
        matches = 0
        for _ in range(12):
            await _settle_pause(0.15)
            current = await self.identity(client, port)
            if not same_project(first, current):
                raise ValueError("Project/session changed while settling capture context.")
            matches = matches + 1 if current == previous else 0
            if matches >= 2:
                return current
            previous = current
        raise ValueError("Project context did not settle; no image accepted.")

    async def assert_complete(self, client, port: int) -> None:
        current = await self.identity(client, port)
        pending = [
            r["review_id"]
            for r in self.records.values()
            if not self.resolved(r)
            and (r.get("context") is None or same_project(r.get("context"), current))
        ]
        if pending:
            raise ValueError(
                f"Visual inspection is incomplete: {pending}. "
                "Capture the correct context and inspect before final saving."
            )

    def resolved(self, record: dict) -> bool:
        if record.get("status") in {"passed", "preview_only"}:
            return True
        if record.get("status") != "superseded":
            return False
        link = record.get("supersession", {})
        replacement = self.records.get(link.get("replacement_review_id"), {})
        return bool(
            replacement.get("status") == "passed"
            and replacement.get("assessment") == link.get("replacement_assessment")
            and same_project(record.get("context"), replacement.get("context"))
        )

    async def supersede(self, client, review_ids, replacement_review_id, port, observation):
        """Resolve obsolete attempts by reference, never approve their old outcome."""
        if (
            not 1 <= len(review_ids) <= 50
            or len(set(review_ids)) != len(review_ids)
            or replacement_review_id in review_ids
            or len(observation.strip()) < 40
        ):
            raise ValueError(
                "Choose 1-50 distinct obsolete reviews and explain coverage/correction."
            )
        current = await self.identity(client, port)
        replacement = self.get(replacement_review_id, client, port)
        assessment = replacement.get("assessment", {})
        evidence = next(
            (
                e
                for e in replacement.get("evidence", [])
                if e["evidence_id"] == assessment.get("evidence_id")
            ),
            None,
        )
        if (
            replacement.get("status") != "passed"
            or not evidence
            or evidence["context"] != current
            or not all(
                assessment.get(k)
                for k in ("context_correct", "framing_sufficient", "readable", "full_coverage")
            )
            or hashlib.sha256(Path(evidence["path"]).read_bytes()).hexdigest() != evidence["sha256"]
        ):
            raise ValueError("Replacement needs a fresh, intact, passed visual assessment.")
        records = [self.get(key, client, port) for key in review_ids]
        for record in records:
            if (
                record.get("status")
                not in {"needs_correction", "blocked", "awaiting_capture", "awaiting_inspection"}
                or not record.get("context")
                or not same_project(record["context"], current)
                or record.get("required_representation")
                != replacement.get("required_representation")
                or record.get("numeric_reconciliation", {}).get("context") != current
            ):
                raise ValueError(
                    "Obsolete review needs same-project/scope fresh readback reconciliation."
                )
        for record in records:
            record["supersession"] = {
                "replacement_review_id": replacement_review_id,
                "replacement_assessment": dict(assessment),
                "previous_status": record["status"],
                "observation": observation,
                "context": current,
                "actor": "assistant_reported_correction_coverage",
            }
            record.update(status="superseded", task_complete=False)
            self.save(record)
        return {
            "reviews": [self.summary(r) for r in records],
            "replacement_review_id": replacement_review_id,
            "note": "Old attempts were not approved. Final completion depends on the replacement.",
        }

    def sample(self, tool: str, context: dict, before_id: str | None = None) -> str | None:
        for record in reversed(list(self.records.values())):
            if record["review_id"] == before_id:
                continue
            if (
                record.get("tool") == tool
                and record.get("status") == "passed"
                and same_project(record.get("context"), context)
                and record.get("context", {}).get("modificationStamp")
                == context.get("modificationStamp")
            ):
                return record["review_id"]
        return None

    async def start(self, client, name, arguments, port, count) -> dict:
        context, identity_error = None, None
        try:
            context = await self.identity(client, port)
        except Exception as exc:
            identity_error = str(exc)
        record = {
            "review_id": str(uuid4()),
            "tool": name,
            "port": port,
            "client_session": str(client.session_id),
            "context": context,
            "status": "dispatching",
            "task_complete": False,
            "required_representation": scope_for(name),
            "item_count": count,
            "early_sample_review_id": self.sample(name, context) if context else None,
            "capture_attempts": [],
            "evidence": [],
        }
        if identity_error:
            record["identity_error"] = identity_error
        self.save(record)  # A disk failure prevents the write.
        self.records[record["review_id"]] = record
        return record

    def get(self, review_id: str, client, port: int) -> dict:
        record = self.records.get(review_id)
        if not record or record.get("port") != port:
            raise ValueError("Visual review does not belong to this port/session.")
        if record.get("client_session") != str(client.session_id):
            raise ValueError("Old MCP session: use capture_visual_review to resume explicitly.")
        return record

    async def capture(
        self, client, review_ids: list[str], port: int, zoom=None, source: str = "auto"
    ) -> CallToolResult:
        if not 1 <= len(review_ids) <= 50:
            raise ValueError("Pass 1 to 50 visual review IDs.")
        records = []
        try:
            current = await self.identity(client, port)
            identity_error = None
        except Exception as exc:
            current = {}
            identity_error = str(exc)
        for key in review_ids:
            record = self.records.get(key)
            if not record or record.get("port") != port:
                raise ValueError("Unknown visual review or wrong port.")
            if record.get("status") == "superseded":
                raise ValueError("Superseded reviews are historical; inspect the replacement.")
            if current and record.get("context") and not same_project(record["context"], current):
                raise ValueError("The reviewed project/session has changed.")
            records.append(record)
        attempts, image = [], None
        choices = ["plan", "window", "3d"] if source == "auto" else [source]
        if source == "auto" and any(
            r["required_representation"]
            in {"layout", "data_or_documentation", "navigator_and_saved_view"}
            for r in records
        ):
            choices = ["window", "plan"]
        for capability in choices:
            before = after = None
            try:
                before = await self.capture_context(client, port) if current else {}
                if current and not same_project(current, before):
                    raise ValueError("The reviewed project/session changed before capture.")
                if capability == "plan":
                    raw = await view_image.capture_view_image(client, zoom, port)
                    data = base64.b64decode(raw["png_base64"], validate=True)
                    metadata = {k: v for k, v in raw.items() if k != "png_base64"}
                elif capability == "window":
                    raw = await window_capture.get_archicad_window_image(client, port)
                    data = raw["png"]
                    metadata = {k: v for k, v in raw.items() if k != "png"}
                elif capability == "3d":
                    raw = await scenes._addon(client, port, "Get3DWindowImage", {"format": "png"})
                    data = base64.b64decode(raw["image"], validate=True)
                    metadata = {"port": port}
                else:
                    raise ValueError("Source must be auto, plan, window or 3d.")
                metrics = inspect_png(data)
                after = await self.identity(client, port) if current else {}
                if current and after != before:
                    raise ValueError("Project changed during capture; discard this image.")
                evidence_id = str(uuid4())
                path = self.root / f"{evidence_id}.png"
                self.root.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                evidence = {
                    "evidence_id": evidence_id,
                    "source": capability,
                    "path": str(path),
                    **metrics,
                    "metadata": metadata,
                    "context": after,
                    "review_ids": review_ids,
                    "requested_zoom": zoom,
                    "requested_zoom_applied": bool(zoom) and capability == "plan",
                }
                attempts.append({"source": capability, "status": "captured"})
                image = ImageContent(
                    type="image", data=base64.b64encode(data).decode(), mimeType="image/png"
                )
                for record in records:
                    record["evidence"].append(evidence)
                    record.update(
                        context=after or None,
                        client_session=str(client.session_id),
                        status="awaiting_inspection",
                        task_complete=False,
                    )
                    if identity_error:
                        record.update(status="blocked", blocker=identity_error)
                break
            except Exception as exc:
                attempt = {"source": capability, "status": "failed", "error": str(exc)}
                if before and after:
                    # Actual values are private runtime evidence, never static fixtures.
                    attempt["changed_context_fields"] = sorted(
                        k for k in before.keys() | after.keys() if before.get(k) != after.get(k)
                    )
                    attempt["before_context"] = before
                    attempt["after_context"] = after
                attempts.append(attempt)
        for record in records:
            record["capture_attempts"].extend(attempts)
            if image is None:
                record.update(
                    status="blocked",
                    task_complete=False,
                    blocker="No acceptable image. Diagnose framing/capabilities; "
                    "try another MCP capture. Task remains incomplete.",
                )
            self.save(record)
        payload = {
            "reviews": [self.summary(r) for r in records],
            "attempts": attempts,
            "note": "Inspect the actual image. A captured image is NOT visual approval. "
            "Reject wrong context, cropped targets, unreadable scale or missing items. "
            "Window/3D fallbacks do NOT apply a requested 2D zoom.",
        }
        return CallToolResult(
            content=[
                TextContent(type="text", text=json.dumps(payload)),
                *([image] if image else []),
            ],
            structuredContent=payload,
        )

    @staticmethod
    def summary(record: dict) -> dict:
        return {
            k: record[k]
            for k in (
                "review_id",
                "status",
                "task_complete",
                "required_representation",
                "item_count",
                "early_sample_review_id",
                "blocker",
                "supersession",
            )
            if k in record
        } | {
            "evidence_ids": [e["evidence_id"] for e in record.get("evidence", [])],
            "instruction": "Look at the returned image and assess context, full coverage, "
            "framing, scale, legibility and actual correctness. "
            "No numeric receipt or hotspot replaces this step.",
        }

    async def assess(
        self,
        client,
        review_ids,
        evidence_id,
        port,
        outcome,
        observation,
        context_correct,
        framing_sufficient,
        readable,
        full_coverage,
        reconciliation_observation: str | None = None,
    ) -> dict:
        if (
            outcome not in {"passed", "needs_correction", "blocked"}
            or len(observation.strip()) < 20
        ):
            raise ValueError("Provide an explicit outcome and a concrete visual observation.")
        current = await self.identity(client, port)
        records = [self.get(key, client, port) for key in review_ids]
        for record in records:
            if record.get("status") == "superseded":
                raise ValueError("Superseded reviews cannot be approved or reassessed.")
            matches = [e for e in record["evidence"] if e["evidence_id"] == evidence_id]
            if len(matches) != 1 or matches[0]["context"] != current:
                raise ValueError("Evidence missing or stale. Capture the correct context again.")
            evidence = matches[0]
            if (
                hashlib.sha256(Path(evidence["path"]).read_bytes()).hexdigest()
                != evidence["sha256"]
            ):
                raise ValueError("Evidence changed on disk; recapture it.")
            if outcome == "passed":
                if not all((context_correct, framing_sufficient, readable, full_coverage)):
                    raise ValueError(
                        "Wrong context/framing/scale/coverage cannot pass visual review."
                    )
                if record["item_count"] > 1 and not record.get("early_sample_review_id"):
                    raise ValueError(
                        "Batch lacks an inspected early sample. Task remains incomplete; "
                        "do not repeat the batch. Inspect and report the missing sample."
                    )
                if record.get("model_outcome") not in {"verified", "reported", "completed"}:
                    reconciliation = record.get("numeric_reconciliation") or {}
                    if (
                        reconciliation.get("context") != current
                        or not reconciliation_observation
                        or len(reconciliation_observation.strip()) < 20
                    ):
                        raise ValueError(
                            "Failed/unknown writes need fresh readback via "
                            "reconcile_visual_review and a concrete comparison, plus images."
                        )
        for record in records:
            record.update(
                status=outcome,
                task_complete=outcome == "passed",
                assessment={
                    "observation": observation,
                    "evidence_id": evidence_id,
                    "context_correct": context_correct,
                    "framing_sufficient": framing_sufficient,
                    "readable": readable,
                    "full_coverage": full_coverage,
                    "actor": "assistant_reported_visual_assessment",
                    "reconciliation_observation": reconciliation_observation,
                },
            )
            self.save(record)
        return {
            "reviews": [self.summary(r) for r in records],
            "note": "Assessment records the assistant inspection; the server has no vision "
            "model and does not independently certify visual correctness.",
        }
