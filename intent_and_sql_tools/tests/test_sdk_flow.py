from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from intent_and_sql_tools.common.registry import ToolRegistry
from intent_and_sql_tools.common.vanna_base import MockVannaImpl
from intent_and_sql_tools.data_agent_tool.tool import execute_sql
from intent_and_sql_tools.data_agent_tool.vanna_bridge import SQLVanna
from intent_and_sql_tools.intent_tool.intent_tool import IntentVanna, identify_intent
from intent_and_sql_tools.data_agent_tool.visualize_tool import visualize_data


class MockSqlImpl:
    def __init__(self):
        self.generate_sql_calls = 0
        self.run_sql_calls = 0
        self.last_question = None
        self.last_sql = None

    def generate_sql(self, question: str) -> str:
        self.generate_sql_calls += 1
        self.last_question = question
        return "SELECT 1"

    def run_sql(self, sql: str):
        self.run_sql_calls += 1
        self.last_sql = sql
        return [{"ok": True}]

    def train(self, **kwargs):
        return True


def _ensure_registry():
    mapping = {
        "query_metric": "execute_sql",
        "plot_chart": "visualize_data",
    }
    if not ToolRegistry._intent_map:
        ToolRegistry._intent_map.update(mapping)
    return mapping


def test_identify_intent_execute_sql_chain(monkeypatch):
    mapping = _ensure_registry()
    monkeypatch.setattr(
        ToolRegistry,
        "get_tool_name",
        lambda intent: mapping.get(intent, "unknown_tool"),
    )
    mock_impl = MockVannaImpl(
        response='{"intent":"query_metric","payload":{"metrics":["revenue"]}}'
    )
    brain = IntentVanna({}, impl=mock_impl)
    monkeypatch.setattr(
        "intent_and_sql_tools.intent_tool.intent_tool.get_brain",
        lambda: brain,
    )
    envelope = identify_intent("查一下土豪流失")
    assert envelope["next_tool"] == "execute_sql"
    sql_impl = MockSqlImpl()
    hands = SQLVanna({}, impl=sql_impl)
    monkeypatch.setattr(
        "intent_and_sql_tools.data_agent_tool.tool.get_hands",
        lambda: hands,
    )
    result = execute_sql(envelope)
    assert sql_impl.generate_sql_calls == 1
    assert sql_impl.run_sql_calls == 1
    assert result is not None


def test_identify_intent_visualize_chain(monkeypatch):
    mapping = _ensure_registry()
    monkeypatch.setattr(
        ToolRegistry,
        "get_tool_name",
        lambda intent: mapping.get(intent, "unknown_tool"),
    )
    mock_impl = MockVannaImpl(
        response='{"intent":"plot_chart","payload":{"metric":"revenue"}}'
    )
    brain = IntentVanna({}, impl=mock_impl)
    monkeypatch.setattr(
        "intent_and_sql_tools.intent_tool.intent_tool.get_brain",
        lambda: brain,
    )
    envelope = identify_intent("画一张最近流水趋势图")
    assert envelope["next_tool"] == "visualize_data"
    result = visualize_data(envelope)
    assert result["status"] == "mock"
    assert result["summary"]["metric"] == "revenue"


def test_unknown_intent_routes_to_unknown_tool():
    mock_impl = MockVannaImpl(response='{"intent":"not_mapped","payload":{}}')
    brain = IntentVanna({}, impl=mock_impl)
    envelope = brain.generate_envelope("未知意图")
    assert envelope["next_tool"] == "unknown_tool"
    assert envelope["intent"] == "not_mapped"


def test_json_parse_failure_returns_error_envelope():
    mock_impl = MockVannaImpl()
    brain = IntentVanna({}, impl=mock_impl, llm_stub=lambda _: "not json")
    envelope = brain.generate_envelope("json broken")
    assert envelope["intent"] == "unknown"
    assert envelope["next_tool"] == "unknown_tool"
    assert envelope["error"]


def test_registry_duplicate_registration_overrides():
    def _tool_a():
        return "a"

    def _tool_b():
        return "b"

    ToolRegistry.register(intent="dup", tool_name="tool_a")(_tool_a)
    assert ToolRegistry.get_tool_name("dup") == "tool_a"
    ToolRegistry.register(intent="dup", tool_name="tool_b")(_tool_b)
    assert ToolRegistry.get_tool_name("dup") == "tool_b"
