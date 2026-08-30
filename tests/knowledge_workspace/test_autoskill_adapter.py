from __future__ import annotations

import asyncio
import io
import json
import zipfile

import httpx
import pytest

from frontend.server.knowledge_workspace.autoskill import (
    AutoSkillClient,
    AutoSkillConfig,
    AutoSkillProtocolError,
)
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
from frontend.server.knowledge_workspace.zip_validator import (
    SkillZipError,
    extract_skill_from_state_zip,
    normalize_skill_zip,
    validate_skill_zip,
)

OFFICIAL_AUTOSKILL_BASE_URL = "https://test-bytebrain.byted.org"


@pytest.mark.asyncio
async def test_official_autoskill_defaults_to_anonymous_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("KNOWLEDGE_AUTOSKILL_BASE_URL", raising=False)
    monkeypatch.delenv("KNOWLEDGE_AUTOSKILL_TOKEN", raising=False)
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "ok", "state_mode": "stateful"})

    config = AutoSkillConfig.from_env()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = AutoSkillClient(config, client=http)
        assert (await client.health())["status"] == "ok"

    assert config.base_url == OFFICIAL_AUTOSKILL_BASE_URL
    assert config.token is None
    assert "authorization" not in requests[0].headers


def test_production_autoskill_requires_an_explicit_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KNOWLEDGE_AUTOSKILL_ENVIRONMENT", "production")
    monkeypatch.delenv("KNOWLEDGE_AUTOSKILL_BASE_URL", raising=False)

    with pytest.raises(
        AutoSkillProtocolError,
        match="production AutoSkill base URL is not configured",
    ):
        AutoSkillConfig.from_env()


def test_production_autoskill_accepts_an_explicit_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KNOWLEDGE_AUTOSKILL_ENVIRONMENT", "production")
    monkeypatch.setenv(
        "KNOWLEDGE_AUTOSKILL_BASE_URL",
        "https://autoskill.production.example/",
    )

    assert AutoSkillConfig.from_env().base_url == "https://autoskill.production.example"


@pytest.mark.asyncio
async def test_configured_autoskill_token_is_sent_as_bearer_auth() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "ok", "state_mode": "stateful"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = AutoSkillClient(
            AutoSkillConfig(token="configured-token"),
            client=http,
        )
        assert (await client.health())["status"] == "ok"

    assert requests[0].headers["authorization"] == "Bearer configured-token"


def test_sse_parser_handles_split_frames_heartbeat_and_multiline_data() -> None:
    parser = SseParser()
    assert parser.feed('id: 7\ndata: {"type":"final_') == []
    frames = parser.feed('answer","data":{"answer":"ok"}}\n\n: keepalive\n\n')
    assert frames[0].event_id == "7"
    assert json.loads(frames[0].data)["type"] == "final_answer"
    assert frames[1].heartbeat is True


def test_default_timeouts_allow_long_running_official_skill_generation() -> None:
    config = AutoSkillConfig()

    assert config.timeout_seconds >= 1_800
    assert config.first_event_timeout_seconds >= 180
    assert config.idle_timeout_seconds >= 180


def test_unknown_and_malformed_events_are_archived_but_not_normalized() -> None:
    parser = SseParser()
    unknown = parse_upstream_frame(
        parser.feed('id: u\ndata: {"type":"future_event","data":{"x":1}}\n\n')[0]
    )
    assert unknown is not None
    assert normalize_upstream_event(unknown, invocation_id="inv", cursor=1) is None
    malformed = parse_sse(["id: bad\ndata: {not-json}\n\n"])[0]
    assert malformed.malformed is True
    assert normalize_upstream_event(malformed, invocation_id="inv", cursor=2) is None


def test_normalizes_full_agent_sequence_with_stable_parent_and_call_relationships() -> (
    None
):
    parsed = parse_sse(
        [
            'id: evt-turn\ndata: {"type":"Turn 1","id":1,"data":{"title":"Investigate"}}\n\n',
            'id: evt-plan\ndata: {"type":"Planning","parent_id":1,"data":{"title":"Check source","reasoning":"private chain","tools":[{"name":"search","arguments":{"authorization":"Bearer secret"}}]}}\n\n',
            'id: evt-action\ndata: {"type":"Action","id":"call-7","parent_id":1,"data":{"title":"search","name":"search","call_id":"call-7","arguments":{"query":"safe","token":"secret"}}}\n\n',
            'id: evt-observation\ndata: {"type":"Observation","parent_id":"call-7","data":{"call_id":"call-7","name":"search","ok":true,"output":{"summary":"found","credential":"secret"}}}\n\n',
            'id: evt-final\ndata: {"type":"final_answer","data":{"answer":"# Result"}}\n\n',
        ]
    )

    normalized = [
        normalize_upstream_event(item, invocation_id="inv", cursor=index + 1)
        for index, item in enumerate(parsed)
    ]

    assert [item["type"] for item in normalized] == [
        "turn.started",
        "activity.started",
        "activity.started",
        "activity.completed",
        "assistant.final",
    ]
    assert [item["id"] for item in normalized] == [
        "1",
        "inv:2",
        "call-7",
        "inv:4",
        "inv:5",
    ]
    assert normalized[1]["parent_id"] == "1"
    assert normalized[2]["parent_id"] == "1"
    assert normalized[2]["data"]["call_id"] == "call-7"
    assert normalized[3]["parent_id"] == "call-7"
    assert normalized[3]["data"]["call_id"] == "call-7"
    assert "reasoning" not in json.dumps(normalized)
    assert "secret" not in json.dumps(normalized)
    assert normalized[4]["data"]["content"] == "# Result"


def test_normalizes_assistant_delta_events_for_streaming_ui() -> None:
    parsed = parse_sse(
        [
            'id: d1\ndata: {"type":"assistant_delta","data":{"delta":"hello ","sequence":1}}\n\n',
            'id: d2\ndata: {"type":"assistant.delta","data":{"text":"world","index":2,"token":"secret"}}\n\n',
        ]
    )

    normalized = [
        normalize_upstream_event(item, invocation_id="inv", cursor=index + 1)
        for index, item in enumerate(parsed)
    ]

    assert [item["type"] for item in normalized] == [
        "assistant.delta",
        "assistant.delta",
    ]
    assert normalized[0]["data"] == {"text": "hello ", "sequence": 1, "final": False}
    assert normalized[1]["data"] == {"text": "world", "sequence": 2, "final": False}
    assert "secret" not in json.dumps(normalized)


def test_normalizes_official_autoskill_event_shape_without_transport_id_breaking_tree() -> (
    None
):
    parsed = parse_sse(
        [
            'id: 0\ndata: {"type":"Turn 1","id":1,"parent_id":null,"data":{"title":"mcp_lookup"}}\n\n',
            'id: 1\ndata: {"type":"Planning","id":null,"parent_id":1,"data":{"title":"Calling 1 tool(s): mcp_lookup","text":"private scratch text","reasoning":"private chain","tools":[{"name":"mcp_lookup","arguments":{"url":"http://127.0.0.1:3417/private"}}]}}\n\n',
            'id: 2\ndata: {"type":"Action","id":"call-real","parent_id":1,"data":{"title":"mcp_lookup","name":"mcp_lookup","call_id":"call-real","arguments":{"authorization":"Bearer secret"}}}\n\n',
            'id: 3\ndata: {"type":"Observation","id":null,"parent_id":"call-real","data":{"call_id":"call-real","name":"mcp_lookup","ok":true,"output":"raw payload"}}\n\n',
        ]
    )

    normalized = [
        normalize_upstream_event(item, invocation_id="inv", cursor=index + 1)
        for index, item in enumerate(parsed)
    ]

    assert normalized[0]["id"] == "1"
    assert normalized[1]["parent_id"] == normalized[0]["id"]
    assert normalized[1]["data"]["steps"] == [
        {"id": "step-1", "label": "mcp_lookup", "status": "running"}
    ]
    assert normalized[2]["parent_id"] == normalized[0]["id"]
    assert normalized[2]["data"]["call_id"] == "call-real"
    assert normalized[3]["parent_id"] == normalized[2]["data"]["call_id"]
    assert normalized[3]["data"]["call_id"] == normalized[2]["data"]["call_id"]
    assert "private scratch text" not in json.dumps(normalized)
    assert "private chain" not in json.dumps(normalized)
    assert "127.0.0.1" not in json.dumps(normalized)
    assert "raw payload" not in json.dumps(normalized)
    assert "duration_ms" not in normalized[3]["data"]


def test_planning_drops_unlabelled_structured_items_instead_of_stringifying_payloads() -> (
    None
):
    event = parse_sse(
        [
            'id: 0\ndata: {"type":"Planning","parent_id":1,"data":{"tools":[{"arguments":{"password":"secret"}},{"name":"safe_tool","arguments":{"query":"private"}}]}}\n\n',
        ]
    )[0]

    normalized = normalize_upstream_event(event, invocation_id="inv", cursor=1)

    assert normalized["data"]["steps"] == [
        {"id": "step-2", "label": "safe_tool", "status": "running"}
    ]
    assert "secret" not in json.dumps(normalized)
    assert "private" not in json.dumps(normalized)


def test_request_summary_and_state_update_keep_distinct_safe_semantics() -> None:
    parsed = parse_sse(
        [
            'id: summary-1\ndata: {"type":"request_summary","data":{"status":"succeeded","model":{"model_name":"GPT-5.5"},"counts":{"used":2,"created":1},"usage":{"total_tokens":42},"authorization":"Bearer secret","lease_id":"lease-secret"}}\n\n',
            'id: state-1\ndata: {"type":"state_update","data":{"state_ready":true,"remote_saved":true,"internal_url":"http://127.0.0.1:3417/private"}}\n\n',
        ]
    )

    summary = normalize_upstream_event(parsed[0], invocation_id="inv", cursor=1)
    state = normalize_upstream_event(parsed[1], invocation_id="inv", cursor=2)

    assert summary["type"] == "request.summary"
    assert summary["data"]["status"] == "succeeded"
    assert summary["data"]["model"] == "GPT-5.5"
    assert summary["data"]["skills"] == {"used": 2, "created": 1, "updated": 0}
    assert summary["data"]["usage"]["total_tokens"] == 42
    assert state["type"] == "state.updated"
    assert state["data"] == {"state_ready": True, "remote_saved": True}
    assert "secret" not in json.dumps([summary, state])
    assert "127.0.0.1" not in json.dumps([summary, state])


def test_state_update_preserves_only_flags_the_provider_actually_sent() -> None:
    remote_saved = parse_sse(
        [
            'id: state-1\ndata: {"type":"state_update","data":{"remote_saved":true}}\n\n',
        ]
    )[0]
    state_ready = parse_sse(
        [
            'id: state-2\ndata: {"type":"state_update","data":{"state_ready":false,"error":"save failed at http://localhost:9000/private"}}\n\n',
        ]
    )[0]

    remote = normalize_upstream_event(remote_saved, invocation_id="inv", cursor=1)
    failed = normalize_upstream_event(state_ready, invocation_id="inv", cursor=2)

    assert remote["data"] == {"remote_saved": True}
    assert failed["data"]["state_ready"] is False
    assert failed["data"]["error_summary"] == "save failed at [INTERNAL_URL]"


def test_skill_zip_requires_single_skillhub_root_and_rejects_slip_and_symlink() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("skillhub/demo/SKILL.md", "# Demo\n")
        archive.writestr("skillhub/demo/scripts/main.py", "print('ok')\n")
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

    legacy = io.BytesIO()
    with zipfile.ZipFile(legacy, "w") as archive:
        archive.writestr("skillhub/demo/SKILL.md", "# Demo\n")
        archive.writestr("skillhub/demo/BuildPlan.json", "{}")
    with pytest.raises(SkillZipError) as error:
        validate_skill_zip(legacy.getvalue())
    assert error.value.code == "SKILL_ZIP_UNSUPPORTED_ENTRY"
    assert "BuildPlan.json" in str(error.value)


def test_skill_zip_normalizes_observed_autoskill_runtime_residue() -> None:
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("skillhub/demo/.pytest_cache/README.md", "cache")
        archive.writestr("skillhub/demo/__pycache__/runner.pyc", b"bytecode")
        archive.writestr("skillhub/demo/SKILL.md", "# Demo\n")
        archive.writestr("skillhub/demo/pytest.ini", "[pytest]\n")
        archive.writestr("skillhub/demo/scripts/run.py", "print('ok')\n")

    with pytest.raises(SkillZipError) as error:
        validate_skill_zip(source.getvalue())
    assert error.value.code == "SKILL_ZIP_UNSUPPORTED_ENTRY"
    assert ".pytest_cache/README.md" in str(error.value)

    normalized = normalize_skill_zip(source.getvalue())
    checked = validate_skill_zip(normalized)
    assert checked["paths"] == (
        "skillhub/demo/SKILL.md",
        "skillhub/demo/scripts/run.py",
    )


def test_skill_zip_normalization_does_not_hide_unknown_runtime_entries() -> None:
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("skillhub/demo/SKILL.md", "# Demo\n")
        archive.writestr("skillhub/demo/output_files/report.html", "<p>bad</p>")

    with pytest.raises(SkillZipError) as error:
        normalize_skill_zip(source.getvalue())
    assert error.value.code == "SKILL_ZIP_UNSUPPORTED_ENTRY"
    assert "output_files/report.html" in str(error.value)


def test_skill_zip_accepts_output_presentation_directory() -> None:
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("skillhub/demo/SKILL.md", "# Demo\n")
        archive.writestr(
            "skillhub/demo/output/semantic_browser.html",
            "<!doctype html><html><body>live presentation</body></html>",
        )

    checked = validate_skill_zip(normalize_skill_zip(source.getvalue()))

    assert "skillhub/demo/output/semantic_browser.html" in checked["paths"]


def test_skill_zip_accepts_standard_presentation_directory() -> None:
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("skillhub/demo/SKILL.md", "# Demo\n")
        archive.writestr(
            "skillhub/demo/presentation/schema_browser.html",
            "<!doctype html><html><body>live presentation</body></html>",
        )

    checked = validate_skill_zip(normalize_skill_zip(source.getvalue()))

    assert "skillhub/demo/presentation/schema_browser.html" in checked["paths"]


def test_state_zip_extracts_only_requested_skill_subtree() -> None:
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("skillhub/other/SKILL.md", "# Other\n")
        archive.writestr("skillhub/demo/SKILL.md", "# Demo\n")
        archive.writestr("skillhub/demo/scripts/run.py", "print('ok')\n")
        archive.writestr("provider/runtime.json", "{}")

    extracted = extract_skill_from_state_zip(source.getvalue(), "demo")
    checked = validate_skill_zip(extracted)
    assert checked["skill_name"] == "demo"
    assert checked["paths"] == (
        "skillhub/demo/SKILL.md",
        "skillhub/demo/scripts/run.py",
    )


def test_skill_zip_accepts_declared_presentation_and_semantic_data_files() -> None:
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("skillhub/demo/SKILL.md", "# Demo\n")
        archive.writestr("skillhub/demo/presentation.html", "<!doctype html>")
        archive.writestr("skillhub/demo/schema_glossary.json", "{}")
        archive.writestr("skillhub/demo/query_results.csv", "id\n1\n")

    checked = validate_skill_zip(source.getvalue())
    assert "skillhub/demo/presentation.html" in checked["paths"]
    assert "skillhub/demo/schema_glossary.json" in checked["paths"]
    assert "skillhub/demo/query_results.csv" in checked["paths"]


def test_skill_zip_accepts_any_root_level_presentation_html_name() -> None:
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("skillhub/demo/SKILL.md", "# Demo\n")
        archive.writestr("skillhub/demo/semantic_browser.html", "<!doctype html>")

    checked = validate_skill_zip(source.getvalue())
    assert "skillhub/demo/semantic_browser.html" in checked["paths"]


def test_skill_zip_accepts_root_level_glossary_json() -> None:
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("skillhub/demo/SKILL.md", "# Demo\n")
        archive.writestr("skillhub/demo/glossary.json", "{}")

    checked = validate_skill_zip(source.getvalue())
    assert "skillhub/demo/glossary.json" in checked["paths"]


@pytest.mark.parametrize(
    ("entry", "code"),
    [
        ("skillhub/demo/../escape", "SKILL_STATE_UNSAFE_PATH"),
        ("skillhub/demo/../../escape", "SKILL_STATE_UNSAFE_PATH"),
    ],
)
def test_state_zip_rejects_unsafe_paths(entry: str, code: str) -> None:
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("skillhub/demo/SKILL.md", "# Demo\n")
        archive.writestr(entry, "bad")

    with pytest.raises(SkillZipError) as error:
        extract_skill_from_state_zip(source.getvalue(), "demo")
    assert error.value.code == code
    assert "skillhub/demo" in str(error.value)


def test_state_zip_rejects_duplicate_paths_case_insensitively() -> None:
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("skillhub/demo/SKILL.md", "# Demo\n")
        archive.writestr("skillhub/demo/skill.md", "collision")

    with pytest.raises(SkillZipError) as error:
        extract_skill_from_state_zip(source.getvalue(), "demo")
    assert error.value.code == "SKILL_STATE_DUPLICATE_PATH"
    assert "skill.md" in str(error.value)


def test_state_zip_rejects_symlinks() -> None:
    source = io.BytesIO()
    info = zipfile.ZipInfo("skillhub/demo/link")
    info.external_attr = (0o120777 << 16) | 0xA000
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("skillhub/demo/SKILL.md", "# Demo\n")
        archive.writestr(info, "target")

    with pytest.raises(SkillZipError) as error:
        extract_skill_from_state_zip(source.getvalue(), "demo")
    assert error.value.code == "SKILL_STATE_SPECIAL_FILE"
    assert "skillhub/demo/link" in str(error.value)


def test_state_zip_requires_requested_target() -> None:
    source = io.BytesIO()
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("skillhub/other/SKILL.md", "# Other\n")

    with pytest.raises(SkillZipError) as error:
        extract_skill_from_state_zip(source.getvalue(), "demo")
    assert error.value.code == "SKILL_STATE_TARGET_MISSING"
    assert "skillhub/demo/" in str(error.value)


def test_html_policy_allows_real_static_html_and_rejects_active_content() -> None:
    safe = b"<!doctype html><html><body><style>body{color:red}</style>ok</body></html>"
    metadata = validate_html_artifact(safe)
    assert metadata["media_type"] == "text/html"
    assert metadata["encoding"] == "utf-8"
    assert metadata["sandbox"] == "allow-scripts"

    with pytest.raises(HtmlArtifactError) as error:
        validate_html_artifact(b"<html><body onclick='alert(1)'>bad</body></html>")
    assert error.value.code == "ARTIFACT_UNSAFE"
    with pytest.raises(HtmlArtifactError) as error:
        validate_html_artifact(b'<html><img srcset="//example.com/a 1x"></html>')
    assert error.value.code == "ARTIFACT_EXTERNAL_LINK"
    with pytest.raises(HtmlArtifactError) as error:
        validate_html_artifact(b"<html><script>fetch('/secret')</script></html>")
    assert error.value.code == "ARTIFACT_UNSAFE"


def test_html_policy_allows_isolated_inline_interactions() -> None:
    safe = b"""<!doctype html><html><body>
    <button id="refresh">Refresh</button>
    <div id="status">ready</div>
    <script>
    const rows = [{name: "north", value: 12}];
    document.getElementById("refresh").addEventListener("click", () => {
      document.getElementById("status").textContent = String(rows.length);
    });
    </script>
    </body></html>"""

    metadata = validate_html_artifact(safe)

    assert metadata["media_type"] == "text/html"
    assert "connect-src 'none'" in metadata["csp"]


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
        create = [
            item
            async for item in client.command(
                "create_skill",
                agent_id="agent",
                session_id="session",
                request_id="request",
                prompt="make a skill",
            )
        ]
        listed = [
            item
            async for item in client.command(
                "list_skill",
                agent_id="agent",
                session_id="session",
                request_id="request",
            )
        ]
    assert [item.event_type for item in create] == ["done"]
    assert [item.event_type for item in listed] == ["done"]
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_find_skill_uses_documented_multipart_post_form() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/find_skill")
        assert not request.url.params
        assert request.headers["content-type"].startswith("multipart/form-data;")
        assert b'name="agent_id"' in request.content
        assert b"agent" in request.content
        assert b'name="session_id"' in request.content
        assert b"session" in request.content
        assert b'name="request_id"' in request.content
        assert b"request" in request.content
        assert b'name="prompt"' in request.content
        assert b"demo" in request.content
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
            item
            async for item in client.find_skill(
                agent_id="agent",
                session_id="session",
                request_id="request",
                prompt="demo",
            )
        ]
    assert [item.event_type for item in items] == ["done"]


@pytest.mark.asyncio
async def test_create_update_and_invoke_send_invocation_policy_as_json_form_field() -> (
    None
):
    requests: list[httpx.Request] = []
    policy = {
        "version": 1,
        "allowed_mcp_servers": ["knowledge-connection-1"],
        "allowed_mcp_tools": ["mcp__knowledge-connection-1__execute_action"],
        "allowed_action_ids": ["fixture.read"],
        "required_successful_calls": [{"arguments": {}, "min_successes": 1}],
        "fail_if_unsatisfied": True,
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = request.content
        assert b'name="invocation_policy"' in body
        assert b'"allowed_action_ids":["fixture.read"]' in body
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
        for call in (
            client.command(
                "create_skill",
                agent_id="agent",
                session_id="session",
                request_id="request-create",
                prompt="make a skill",
                invocation_policy=policy,
            ),
            client.command(
                "update_skill",
                agent_id="agent",
                session_id="session",
                request_id="request-update",
                prompt="update a skill",
                invocation_policy=policy,
            ),
            client.invoke(
                agent_id="agent",
                session_id="session",
                request_id="request-run",
                message="run the skill",
                invocation_policy=policy,
            ),
        ):
            assert [item.event_type async for item in call] == ["done"]

    assert [request.url.path.rsplit("/", 1)[-1] for request in requests] == [
        "create_skill",
        "update_skill",
        "invoke",
    ]


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
            item
            async for item in client.list_skill(
                agent_id="agent",
                session_id="session",
                request_id="request",
            )
        ]
    assert [item.event_type for item in items] == ["final_answer", "done"]
    assert '"demo"' in str(items[0].payload)


@pytest.mark.asyncio
async def test_stream_reconnects_with_last_event_id_and_enforces_total_timeout() -> (
    None
):
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/stream"):
            assert request.headers["last-event-id"] == "upstream-7"
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=b'id: upstream-8\ndata: {"type":"done","data":{}}\n\n',
            )
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=b""
        )

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
            item
            async for item in client.reconnect(
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
            yield b'data: {"type":"done","data":{}}\n\n'

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
            _ = [
                item
                async for item in client.invoke(
                    agent_id="agent",
                    session_id="session",
                    request_id="request",
                    message="slow",
                )
            ]


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
            _ = [
                item
                async for item in client.invoke(
                    agent_id="agent",
                    session_id="session",
                    request_id="request",
                    message="partial",
                )
            ]


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
            body = json.dumps(
                {"data": {"state_zip_b64": base64.b64encode(state).decode()}}
            )
            return httpx.Response(200, json=json.loads(body))
        assert b'name="state"; filename="state.zip"' in request.content
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b'data: {"type":"done","data":{}}\n\n',
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = AutoSkillClient(
            AutoSkillConfig(
                base_url="http://localhost", token="test-token", state_mode="stateless"
            ),
            client=http,
        )
        items = [
            item
            async for item in client.invoke(
                agent_id="agent",
                session_id="session",
                request_id="request",
                message="continue",
                state=state,
            )
        ]
        decoded = await client.get_state_zip(
            agent_id="agent", session_id="session", request_id="request"
        )
    assert [item.event_type for item in items] == ["done"]
    assert decoded == state
    assert requests[0].url.path.endswith("/invoke_stateless")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "prompt", "name", "expected"),
    [
        ("create_skill", "create prompt", None, "/create-skill create prompt"),
        ("update_skill", "update prompt", None, "/update-skill update prompt"),
        ("find_skill", "find prompt", None, "/find-skill find prompt"),
        ("view_skill", None, "demo", "/view-skill demo"),
        ("list_skill", None, None, "/list-skill"),
    ],
)
async def test_stateless_named_commands_preserve_slash_message_and_fields(
    command: str,
    prompt: str | None,
    name: str | None,
    expected: str,
) -> None:
    requests: list[httpx.Request] = []
    state = b"PK\x03\x04state"

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = await request.aread()
        assert b'name="state"; filename="state.zip"' in body
        assert b'name="model"' in body
        assert b'name="invocation_policy"' in body
        assert b'name="agent_id"' in body
        assert b'name="session_id"' in body
        assert b'name="request_id"' in body
        assert f'name="message"\r\n\r\n{expected}'.encode() in body
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b'data: {"type":"done","data":{}}\n\n',
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = AutoSkillClient(
            AutoSkillConfig(
                base_url="http://localhost",
                state_mode="stateless",
            ),
            client=http,
        )
        items = [
            item
            async for item in client.command(
                command,
                agent_id="agent",
                session_id="session",
                request_id="request",
                prompt=prompt,
                name=name,
                model="model-id",
                state=state,
                invocation_policy={"allowed_action_ids": ["read"]},
            )
        ]

    assert [item.event_type for item in items] == ["done"]
    assert len(requests) == 1


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
