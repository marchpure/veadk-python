from __future__ import annotations

import io
import json
import zipfile

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
from frontend.server.knowledge_workspace.autoskill import AutoSkillClient, AutoSkillConfig


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
