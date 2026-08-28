"""Strict SSE parsing and provider-event normalization."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class SseFrame:
    event_id: str | None
    event: str | None
    data: str
    heartbeat: bool = False


@dataclass(frozen=True)
class ParsedUpstreamEvent:
    event_id: str | None
    event_type: str
    payload: Mapping[str, Any]
    raw: str
    malformed: bool = False


_SECRET_KEYS = {
    "access_key",
    "access_key_id",
    "api_key",
    "authorization",
    "cookie",
    "credential",
    "password",
    "secret",
    "secret_key",
    "session_token",
    "token",
}
_SECRET_ASSIGNMENT = re.compile(
    r"""(?i)["']?(?:api[_-]?key|access[_-]?key|authorization|cookie|credential|password|secret|session[_-]?token|token)["']?\s*[:=]\s*(?:["']?bearer\s+)?["']?[^\s,;}"']+"""
)
_SECRET_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")


def sanitize_event_payload(value: Any, *, key: str = "", depth: int = 0) -> Any:
    """Bound and redact provider payloads before durable raw-event storage."""

    normalized = key.casefold().replace("-", "_")
    if normalized in _SECRET_KEYS or normalized.endswith(
        ("_token", "_secret", "_password")
    ):
        return "[REDACTED]"
    if depth >= 6:
        return "[TRUNCATED]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        bounded = value[:8_000]
        bounded = _SECRET_ASSIGNMENT.sub("[REDACTED]", bounded)
        return _SECRET_BEARER.sub("[REDACTED]", bounded)
    if isinstance(value, Mapping):
        return {
            str(item_key)[:160]: sanitize_event_payload(
                item, key=str(item_key), depth=depth + 1
            )
            for item_key, item in list(value.items())[:64]
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_event_payload(item, depth=depth + 1) for item in value[:64]]
    return "[UNSUPPORTED]"


class SseParser:
    """Incremental parser tolerant of comments and split TCP chunks."""

    def __init__(self, *, max_buffer_bytes: int = 2 * 1024 * 1024) -> None:
        self._event_id: str | None = None
        self._event_name: str | None = None
        self._data: list[str] = []
        self._line_buffer = ""
        self._max_buffer_bytes = max_buffer_bytes

    def feed(self, chunk: str | bytes) -> list[SseFrame]:
        text = (
            chunk.decode("utf-8", errors="replace")
            if isinstance(chunk, bytes)
            else chunk
        )
        frames: list[SseFrame] = []
        self._line_buffer += text
        if len(self._line_buffer.encode("utf-8")) > self._max_buffer_bytes:
            raise ValueError("SSE frame exceeds configured buffer limit")
        lines = self._line_buffer.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self._line_buffer = lines.pop() or ""
        if (
            sum(len(item.encode("utf-8")) for item in self._data)
            > self._max_buffer_bytes
        ):
            raise ValueError("SSE data exceeds configured buffer limit")
        for line in lines:
            if line == "":
                if self._data:
                    data = "\n".join(self._data)
                    if len(data.encode("utf-8")) > self._max_buffer_bytes:
                        raise ValueError("SSE frame exceeds configured buffer limit")
                    frames.append(SseFrame(self._event_id, self._event_name, data))
                elif self._event_id is None and self._event_name is None:
                    frames.append(SseFrame(None, None, "", heartbeat=True))
                self._event_id = self._event_name = None
                self._data = []
                continue
            if line.startswith(":"):
                frames.append(SseFrame(None, None, "", heartbeat=True))
                continue
            field, _, value = line.partition(":")
            if value.startswith(" "):
                value = value[1:]
            if field == "id":
                self._event_id = value
            elif field == "event":
                self._event_name = value
            elif field == "data":
                self._data.append(value)
                if (
                    sum(len(item.encode("utf-8")) for item in self._data)
                    > self._max_buffer_bytes
                ):
                    raise ValueError("SSE data exceeds configured buffer limit")
        return frames

    def finish(self) -> list[SseFrame]:
        if self._line_buffer:
            frames = self.feed("\n")
        else:
            frames = []
        if not self._data:
            return frames
        data = "\n".join(self._data)
        if len(data.encode("utf-8")) > self._max_buffer_bytes:
            raise ValueError("SSE frame exceeds configured buffer limit")
        frame = SseFrame(self._event_id, self._event_name, data)
        self._event_id = self._event_name = None
        self._data = []
        return frames + [frame]


def parse_upstream_frame(frame: SseFrame) -> ParsedUpstreamEvent | None:
    if frame.heartbeat or not frame.data:
        return None
    try:
        value = json.loads(frame.data)
    except json.JSONDecodeError:
        return ParsedUpstreamEvent(
            frame.event_id,
            frame.event or "unknown",
            {"raw": sanitize_event_payload(frame.data)},
            sanitize_event_payload(frame.data),
            True,
        )
    if not isinstance(value, Mapping):
        return ParsedUpstreamEvent(
            frame.event_id, frame.event or "unknown", {"value": value}, frame.data, True
        )
    event_type = str(value.get("type") or frame.event or "unknown")
    return ParsedUpstreamEvent(
        frame.event_id, event_type, sanitize_event_payload(value), frame.data
    )


def _data(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = value.get("data")
    return dict(payload) if isinstance(payload, Mapping) else {"value": payload}


def _plan_steps(value: Any) -> list[dict[str, str]]:
    values = [value] if isinstance(value, str) else value
    if not isinstance(values, list):
        values = []
    result: list[dict[str, str]] = []
    valid_statuses = {"pending", "running", "completed", "failed", "cancelled"}
    for index, item in enumerate(values):
        if isinstance(item, Mapping):
            status = str(item.get("status") or "running").casefold()
            result.append(
                {
                    "id": str(
                        item.get("id") or item.get("step_id") or f"step-{index + 1}"
                    ),
                    "label": str(
                        item.get("label")
                        or item.get("name")
                        or item.get("description")
                        or item
                    ),
                    "status": status if status in valid_statuses else "running",
                }
            )
        else:
            result.append(
                {"id": f"step-{index + 1}", "label": str(item), "status": "running"}
            )
    return result


def _duration_ms(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _identifier(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:256] if text else None


def _safe_summary(value: Any, *, limit: int = 2_000) -> str:
    """Return display-safe summary text without exposing structured payloads."""

    if not isinstance(value, str):
        return ""
    return str(sanitize_event_payload(value))[:limit]


def _non_negative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def normalize_upstream_event(
    event: ParsedUpstreamEvent,
    *,
    invocation_id: str,
    cursor: int,
) -> dict[str, Any] | None:
    """Return a STEP 1 event, or ``None`` for an archived-only provider event."""

    now = datetime.now(timezone.utc).isoformat()
    data = _data(event.payload)
    kind = event.event_type.casefold().replace("-", "_")
    is_turn = re.fullmatch(r"turn[ _]+\d+", kind) is not None
    base = {
        "id": event.event_id
        or _identifier(event.payload.get("id"))
        or f"{invocation_id}:{cursor}",
        "invocation_id": invocation_id,
        "occurred_at": now,
    }
    parent_id = _identifier(event.payload.get("parent_id"))
    if parent_id is not None:
        base["parent_id"] = parent_id
    if event.malformed or (not is_turn and kind not in {
        "planning",
        "action",
        "observation",
        "final_answer",
        "request_summary",
        "state_update",
        "error",
        "done",
    }):
        return None
    if is_turn:
        turn_number = int(re.search(r"\d+", kind).group())
        return {
            **base,
            "type": "turn.started",
            "data": {
                "turn_number": turn_number,
                "title": _safe_summary(data.get("title"), limit=256)
                or f"Turn {turn_number}",
                "status": "running",
            },
        }
    if kind == "planning":
        steps = _plan_steps(data.get("steps") or data.get("plan") or [])
        return {
            **base,
            "type": "activity.started",
            "data": {
                "activity_id": str(base["id"]),
                "activity_kind": "planning",
                "title": _safe_summary(data.get("title"), limit=256)
                or "Planning",
                "status": "running",
                "summary": _safe_summary(data.get("summary") or data.get("text")),
                "steps": steps,
            },
        }
    if kind == "action":
        call_id = (
            _identifier(data.get("call_id"))
            or _identifier(event.payload.get("id"))
            or str(base["id"])
        )
        action = str(
            data.get("status") or data.get("phase") or data.get("event") or "started"
        ).casefold()
        tool = str(
            data.get("tool_name")
            or data.get("tool")
            or data.get("name")
            or "autoskill.action"
        )
        if action in {
            "completed",
            "complete",
            "end",
            "finished",
            "failed",
            "cancelled",
        }:
            return {
                **base,
                "type": "activity.completed",
                "data": {
                    "activity_id": call_id,
                    "activity_kind": "tool",
                    "call_id": call_id,
                    "tool_name": tool,
                    "status": "failed"
                    if action == "failed"
                    else action
                    if action in {"cancelled", "succeeded"}
                    else "succeeded",
                    "duration_ms": _duration_ms(data.get("duration_ms")),
                    "output_summary": _safe_summary(data.get("output_summary")),
                },
            }
        return {
            **base,
            "type": "activity.started",
            "data": {
                "activity_id": call_id,
                "activity_kind": "tool",
                "call_id": call_id,
                "tool_name": tool,
                "status": "running",
                "input_summary": _safe_summary(data.get("input_summary")),
            },
        }
    if kind == "observation":
        call_id = (
            _identifier(data.get("call_id"))
            or parent_id
            or _identifier(event.payload.get("id"))
            or str(base["id"])
        )
        return {
            **base,
            "type": "activity.completed",
            "data": {
                "activity_id": call_id,
                "activity_kind": "tool",
                "call_id": call_id,
                "tool_name": str(
                    data.get("tool_name")
                    or data.get("name")
                    or "autoskill.observation"
                ),
                "status": "succeeded" if data.get("ok", True) else "failed",
                "duration_ms": _duration_ms(data.get("duration_ms")),
                "output_summary": _safe_summary(
                    data.get("summary") or data.get("output_summary")
                ),
                "error_summary": _safe_summary(data.get("error")),
            },
        }
    if kind == "final_answer":
        text = data.get("answer", data.get("text", data.get("content", "")))
        return {
            **base,
            "type": "assistant.final",
            "data": {
                "content": str(sanitize_event_payload(text)),
            },
        }
    if kind == "error":
        return {
            **base,
            "type": "run.failed",
            "data": {
                "status": "failed",
                "error": {
                    "code": str(data.get("code") or "AUTOSKILL_ERROR"),
                    "message": str(
                        sanitize_event_payload(
                            data.get("message")
                            or data.get("error")
                            or "AutoSkill error"
                        )
                    )[:2000],
                    "retryable": bool(data.get("retryable", False)),
                },
            },
        }
    if kind == "request_summary":
        model = data.get("model")
        counts = data.get("counts")
        usage = data.get("usage")
        safe_usage: dict[str, int | float] = {}
        if isinstance(usage, Mapping):
            for key in (
                "total_tokens",
                "total_input_tokens",
                "total_output_tokens",
                "api_elapsed_seconds",
                "total_wall_duration_seconds",
                "total_duration_seconds",
            ):
                value = usage.get(key)
                if isinstance(value, (int, float)) and value >= 0:
                    safe_usage[key] = value
        return {
            **base,
            "type": "request.summary",
            "data": {
                "status": _safe_summary(data.get("status"), limit=64),
                "model": _safe_summary(
                    model.get("model_name") or model.get("model_id")
                    if isinstance(model, Mapping)
                    else model,
                    limit=256,
                ),
                "skills": {
                    "used": _non_negative_int(
                        counts.get("used") if isinstance(counts, Mapping) else 0
                    ),
                    "created": _non_negative_int(
                        counts.get("created") if isinstance(counts, Mapping) else 0
                    ),
                    "updated": _non_negative_int(
                        counts.get("updated") if isinstance(counts, Mapping) else 0
                    ),
                },
                "usage": safe_usage,
                "message": _safe_summary(data.get("message")),
            },
        }
    if kind == "state_update":
        return {
            **base,
            "type": "state.updated",
            "data": {
                "state_ready": bool(data.get("state_ready")),
                "remote_saved": bool(data.get("remote_saved")),
            },
        }
    return None


def parse_sse(iterable: Iterable[str | bytes]) -> list[ParsedUpstreamEvent]:
    parser = SseParser()
    result: list[ParsedUpstreamEvent] = []
    for chunk in iterable:
        for frame in parser.feed(chunk):
            parsed = parse_upstream_frame(frame)
            if parsed:
                result.append(parsed)
    for frame in parser.finish():
        parsed = parse_upstream_frame(frame)
        if parsed:
            result.append(parsed)
    return result
