from __future__ import annotations

import io
import json
import zipfile
import asyncio

import httpx
import pytest

from frontend.server.knowledge_workspace.html_artifact import (
    HtmlArtifactError,
    validate_html_artifact,
    validate_output_archive,
)
from frontend.server.knowledge_workspace.sse import (
    SseParser,
    normalize_upstream_event,
    parse_sse,
    parse_upstream_frame,
)
from frontend.server.knowledge_workspace.zip_validator import SkillZipError, validate_skill_zip
from frontend.server.knowledge_workspace.autoskill import (
    AutoSkillClient,
    AutoSkillConfig,
    AutoSkillProtocolError,
)


def test_sse_parser_handles_split_frames_heartbeat_and_multiline_data() -> None:
    parser = SseParser()
    assert parser.feed("id: 7\ndata: {\"type\":\"final_") == []
    frames = parser.feed("answer\",\"data\":{\"answer\":\"ok\"}}\n\n: keepalive\n\n")
    assert frames[0].event_id == "7"
    assert json.loads(frames[0].data)["type"] == "final_answer"
    assert frames[1].heartbeat is True


def test_unknown_and_malformed_events_are_archived_but_not_normalized() -> None:
    parser = SseParser()
    unknown = parse_upstream_frame(parser.feed("id: u\ndata: {\"type\":\"future_event\",\"data\":{\"x\":1}}\n\n")[0])
    assert unknown is not None
    assert normalize_upstream_event(unknown, invocation_id="inv", cursor=1) is None
    malformed = parse_sse(["id: bad\ndata: {not-json}\n\n"])[0]
    assert malformed.malformed is True
    assert normalize_upstream_event(malformed, invocation_id="inv", cursor=2) is None


def test_skill_zip_requires_single_skillhub_root_and_rejects_slip_and_symlink() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("skillhub/demo/SKILL.md", "# Demo\n")
        archive.writestr("skillhub/demo/main.py", "print('ok')\n")
    result = validate_skill_zip(buffer.getvalue())
    assert result["skill_name"] == "demo"
    assert len(result["sha256"]) == 64

    slip = io.BytesIO()
    with zipfile.ZipFile(slip, "w") as archive:
        archive.writestr("skillhub/demo/SKILL.md", "# Demo\n")
        archive.writestr("skillhub/demo/../escape", "bad")
    with pytest.raises(SkillZipError) as error:
        validate_skill_zip(slip.getvalue())
    assert error.value.code == "SKILL_ZIP_UNSAFE_PATH"


def test_html_policy_allows_real_static_html_and_rejects_active_content() -> None:
    safe = b"<!doctype html><html><body><style>body{color:red}</style>ok</body></html>"
    metadata = validate_html_artifact(safe)
    assert metadata["media_type"] == "text/html"
    assert metadata["encoding"] == "utf-8"

    with pytest.raises(HtmlArtifactError) as error:
        validate_html_artifact(b"<html><script>alert(1)</script></html>")
    assert error.value.code == "ARTIFACT_UNSAFE"
    with pytest.raises(HtmlArtifactError) as error:
        validate_html_artifact(b'<html><img srcset="//example.com/a 1x"></html>')
    assert error.value.code == "ARTIFACT_EXTERNAL_LINK"


def test_output_zip_returns_real_html_without_constructing_content() -> None:
    buffer = io.BytesIO()
    html = b"<!doctype html><html><body>real</body></html>"
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("output/report.html", html)
    name, content, metadata = validate_output_archive(buffer.getvalue())
    assert name == "output/report.html"
    assert content == html
    assert metadata["sha256"] != ""


@pytest.mark.asyncio
async def test_command_uses_multipart_form_fields_and_query_for_skill_reads() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = request.content
        if request.url.path.endswith("/list_skill"):
            assert request.method == "GET"
            assert request.url.params["agent_id"] == "agent"
            assert request.url.params["request_id"] == "request"
        else:
            assert request.method == "POST"
            assert b'name="prompt"' in body
            assert b'name="agent_id"' in body
            assert b'name="request_id"' in body
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b'data: {"type":"done","data":{}}\n\n',
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = AutoSkillClient(
            AutoSkillConfig(base_url="http://localhost", token="test-token"),
            client=http,
        )
        create = [item async for item in client.command(
            "create_skill",
            agent_id="agent",
            session_id="session",
            request_id="request",
            prompt="make a skill",
        )]
        listed = [item async for item in client.command(
            "list_skill",
            agent_id="agent",
            session_id="session",
            request_id="request",
        )]
    assert [item.event_type for item in create] == ["done"]
    assert [item.event_type for item in listed] == ["done"]
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_find_skill_uses_documented_query_form() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path.endswith("/find_skill")
        assert request.url.params["prompt"] == "demo"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b'data: {"type":"done","data":{}}\n\n',
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = AutoSkillClient(
            AutoSkillConfig(base_url="http://localhost", token="test-token"),
            client=http,
        )
        items = [
            item async for item in client.find_skill(
                agent_id="agent",
                session_id="session",
                request_id="request",
                prompt="demo",
            )
        ]
    assert [item.event_type for item in items] == ["done"]


@pytest.mark.asyncio
async def test_query_skill_command_accepts_documented_json_envelope() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            json={
                "code": 200,
                "data": {
                    "command": "list-skill",
                    "ok": True,
                    "data": {"skills": [{"name": "demo"}]},
                    "error": None,
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = AutoSkillClient(
            AutoSkillConfig(base_url="http://localhost", token="test-token"),
            client=http,
        )
        items = [
            item async for item in client.list_skill(
                agent_id="agent",
                session_id="session",
                request_id="request",
            )
        ]
    assert [item.event_type for item in items] == ["final_answer", "done"]
    assert '"demo"' in str(items[0].payload)


@pytest.mark.asyncio
async def test_stream_reconnects_with_last_event_id_and_enforces_total_timeout() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/stream"):
            assert request.headers["last-event-id"] == "upstream-7"
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=b"id: upstream-8\ndata: {\"type\":\"done\",\"data\":{}}\n\n",
            )
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=b"")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = AutoSkillClient(
            AutoSkillConfig(
                base_url="http://localhost",
                token="test-token",
                timeout_seconds=0.1,
                first_event_timeout_seconds=0.05,
            ),
            client=http,
        )
        items = [
            item async for item in client.reconnect(
                agent_id="agent",
                session_id="session",
                request_id="request",
                last_event_id="upstream-7",
            )
        ]
    assert [item.event_type for item in items] == ["done"]
    assert requests[0].headers["last-event-id"] == "upstream-7"


@pytest.mark.asyncio
async def test_stream_first_event_timeout_fails_closed() -> None:
    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            await asyncio.sleep(0.05)
            yield b"data: {\"type\":\"done\",\"data\":{}}\n\n"

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=SlowStream(),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = AutoSkillClient(
            AutoSkillConfig(
                base_url="http://localhost",
                token="test-token",
                first_event_timeout_seconds=0.005,
            ),
            client=http,
        )
        with pytest.raises(AutoSkillProtocolError, match="first-event"):
            _ = [item async for item in client.invoke(
                agent_id="agent",
                session_id="session",
                request_id="request",
                message="slow",
            )]


@pytest.mark.asyncio
async def test_stream_disconnect_before_done_fails_closed() -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b'data: {"type":"final_answer","data":{"answer":"partial"}}\n\n',
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = AutoSkillClient(
            AutoSkillConfig(base_url="http://localhost", token="test-token"),
            client=http,
        )
        with pytest.raises(AutoSkillProtocolError, match="disconnected"):
            _ = [item async for item in client.invoke(
                agent_id="agent",
                session_id="session",
                request_id="request",
                message="partial",
            )]


def test_normalization_bounds_invalid_duration_and_plan_status() -> None:
    parsed = parse_sse(
        [
            'data: {"type":"planning","data":{"steps":[{"label":"x","status":"future"}]}}\n\n',
            'data: {"type":"action","data":{"status":"completed","duration_ms":"not-a-number"}}\n\n',
        ]
    )
    plan = normalize_upstream_event(parsed[0], invocation_id="inv", cursor=1)
    action = normalize_upstream_event(parsed[1], invocation_id="inv", cursor=2)
    assert plan["data"]["steps"][0]["status"] == "running"
    assert action["data"]["duration_ms"] == 0


@pytest.mark.asyncio
async def test_stateless_invoke_sends_state_zip_and_get_state_decodes_it() -> None:
    import base64

    state = b"PK\x03\x04state"
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/get_state"):
            body = json.dumps({"data": {"state_zip_b64": base64.b64encode(state).decode()}})
            return httpx.Response(200, json=json.loads(body))
        assert b'name="state"; filename="state.zip"' in request.content
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b'data: {"type":"done","data":{}}\n\n',
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = AutoSkillClient(
            AutoSkillConfig(base_url="http://localhost", token="test-token", state_mode="stateless"),
            client=http,
        )
        items = [
            item async for item in client.invoke(
                agent_id="agent",
                session_id="session",
                request_id="request",
                message="continue",
                state=state,
            )
        ]
        decoded = await client.get_state_zip(agent_id="agent", session_id="session", request_id="request")
    assert [item.event_type for item in items] == ["done"]
    assert decoded == state
    assert requests[0].url.path.endswith("/invoke_stateless")


def test_sse_payload_redacts_inline_bearer_and_secret_assignments() -> None:
    parsed = parse_sse(
        [
            'data: {"type":"observation","data":{"text":"Bearer abc.def token=plain-secret"}}\n\n'
        ]
    )[0]
    assert "[REDACTED]" in parsed.payload["data"]["text"]
    assert "abc.def" not in json.dumps(parsed.payload)
    assert "plain-secret" not in json.dumps(parsed.payload)


def test_malformed_sse_raw_evidence_is_redacted_and_bounded() -> None:
    parsed = parse_sse(["data: {not-json token=plain-secret}\n\n"])[0]
    assert parsed.malformed is True
    assert "plain-secret" not in parsed.raw
    assert "[REDACTED]" in parsed.raw


def test_sse_parser_enforces_complete_frame_size() -> None:
    parser = SseParser(max_buffer_bytes=8)
    with pytest.raises(ValueError, match="buffer limit"):
        parser.feed("data: 123456789\n\n")
