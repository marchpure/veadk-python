"""Strict SSE parsing and provider-event normalization."""

from __future__ import annotations

import json
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
    "access_key", "access_key_id", "api_key", "authorization", "cookie",
    "credential", "password", "secret", "secret_key", "session_token", "token",
}


def sanitize_event_payload(value: Any, *, key: str = "", depth: int = 0) -> Any:
    """Bound and redact provider payloads before durable raw-event storage."""

    normalized = key.casefold().replace("-", "_")
    if normalized in _SECRET_KEYS or normalized.endswith(("_token", "_secret", "_password")):
        return "[REDACTED]"
    if depth >= 6:
        return "[TRUNCATED]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:8_000]
    if isinstance(value, Mapping):
        return {
            str(item_key)[:160]: sanitize_event_payload(item, key=str(item_key), depth=depth + 1)
            for item_key, item in list(value.items())[:64]
        }
    if isinstance(value, (list, tuple)):
        return [sanitize_event_payload(item, depth=depth + 1) for item in value[:64]]
    return "[UNSUPPORTED]"


class SseParser:
    """Incremental parser tolerant of comments and split TCP chunks."""

    def __init__(self) -> None:
        self._event_id: str | None = None
        self._event_name: str | None = None
        self._data: list[str] = []
        self._line_buffer = ""

    def feed(self, chunk: str | bytes) -> list[SseFrame]:
        text = chunk.decode("utf-8", errors="replace") if isinstance(chunk, bytes) else chunk
        frames: list[SseFrame] = []
        self._line_buffer += text
        lines = self._line_buffer.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        self._line_buffer = lines.pop() or ""
        for line in lines:
            if line == "":
                if self._data:
                    frames.append(SseFrame(self._event_id, self._event_name, "\n".join(self._data)))
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
        return frames

    def finish(self) -> list[SseFrame]:
        if self._line_buffer:
            frames = self.feed("\n")
        else:
            frames = []
        if not self._data:
            return frames
        frame = SseFrame(self._event_id, self._event_name, "\n".join(self._data))
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
            frame.event_id, frame.event or "unknown", {"raw": frame.data}, frame.data, True
        )
    if not isinstance(value, Mapping):
        return ParsedUpstreamEvent(
            frame.event_id, frame.event or "unknown", {"value": value}, frame.data, True
        )
    event_type = str(value.get("type") or frame.event or "unknown")
    return ParsedUpstreamEvent(frame.event_id, event_type, sanitize_event_payload(value), frame.data)


def _data(value: Mapping[str, Any]) -> dict[str, Any]:
    payload = value.get("data")
    return dict(payload) if isinstance(payload, Mapping) else {"value": payload}


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
    base = {
        "id": f"{invocation_id}:{cursor}",
        "invocation_id": invocation_id,
        "occurred_at": now,
    }
    if event.malformed or kind not in {
        "planning", "action", "observation", "final_answer",
        "request_summary", "state_update", "error", "done",
    }:
        return None
    if kind == "planning":
        steps = data.get("steps") or data.get("plan") or []
        if isinstance(steps, str):
            steps = [{"id": "plan", "label": steps, "status": "running"}]
        return {**base, "type": "plan.updated", "data": {"steps": list(steps), "summary": data.get("summary", "")}}
    if kind == "action":
        action = str(data.get("status") or data.get("phase") or data.get("event") or "started").casefold()
        tool = str(data.get("tool_name") or data.get("tool") or data.get("name") or "autoskill.action")
        if action in {"completed", "complete", "end", "finished", "failed", "cancelled"}:
            return {**base, "type": "tool.completed", "data": {
                "tool_call_id": str(data.get("tool_call_id") or data.get("id") or f"{invocation_id}:{cursor}"),
                "tool_name": tool, "status": "failed" if action == "failed" else action if action in {"cancelled", "succeeded"} else "succeeded",
                "duration_ms": int(data.get("duration_ms") or 0),
                "output_summary": str(data.get("output_summary") or data.get("output") or "")[:2000],
            }}
        return {**base, "type": "tool.started", "data": {
            "tool_call_id": str(data.get("tool_call_id") or data.get("id") or f"{invocation_id}:{cursor}"),
            "tool_name": tool,
            "input_summary": str(data.get("input_summary") or data.get("input") or "")[:2000],
        }}
    if kind == "observation":
        return {**base, "type": "tool.completed", "data": {
            "tool_call_id": str(data.get("tool_call_id") or data.get("id") or f"{invocation_id}:{cursor}"),
            "tool_name": str(data.get("tool_name") or "autoskill.observation"),
            "status": "succeeded",
            "duration_ms": int(data.get("duration_ms") or 0),
            "output_summary": str(data.get("summary") or data.get("observation") or data.get("output") or "")[:2000],
        }}
    if kind == "final_answer":
        text = data.get("answer", data.get("text", data.get("content", "")))
        return {**base, "type": "assistant.delta", "data": {"text": str(text), "sequence": cursor, "final": True}}
    if kind == "error":
        return {**base, "type": "run.failed", "data": {"status": "failed", "error": {
            "code": str(data.get("code") or "AUTOSKILL_ERROR"),
            "message": str(data.get("message") or data.get("error") or "AutoSkill error")[:2000],
            "retryable": bool(data.get("retryable", False)),
        }}}
    if kind == "request_summary":
        return {**base, "type": "run.summary", "data": sanitize_event_payload(data)}
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
