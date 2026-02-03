from typing import Any

from intent_and_sql_tools.common.registry import ToolRegistry
from intent_and_sql_tools.data_agent_tool.runtime import get_hands


@ToolRegistry.register(intent="query_metric", tool_name="execute_sql")
def execute_sql(envelope: dict) -> str:
    payload = envelope.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {"value": payload}
    rich_prompt = _compile_query_metric(payload)
    hands = get_hands()
    sql = hands.generate_sql(question=rich_prompt)
    df = hands.run_sql(sql)
    if hasattr(df, "to_markdown"):
        return df.to_markdown()
    return str(df)


def _compile_query_metric(payload: dict) -> str:
    metrics = _listify(payload.get("metrics") or payload.get("metric"))
    time_range = payload.get("time_range") or payload.get("timeRange")
    filters = _listify(payload.get("filters"))
    dimensions = _listify(payload.get("dimensions") or payload.get("dims"))
    parts = [
        "Task: Query metrics with strict schema adherence.",
        f"Metrics: {_fmt_list(metrics)}",
        f"TimeRange: {_fmt_value(time_range)}",
        f"Filters: {_fmt_list(filters)}",
        f"Dimensions: {_fmt_list(dimensions)}",
        "Constraints: Use documentation definitions; do not hallucinate columns.",
    ]
    return "\n".join(parts)


def _listify(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return [v for v in value if v not in (None, "")]
    return [value]


def _fmt_list(value: list) -> str:
    return ", ".join([str(v) for v in value]) if value else "None"


def _fmt_value(value: Any) -> str:
    if value in (None, "", []):
        return "None"
    return str(value)
