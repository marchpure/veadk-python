'''
Author: haoxingjun
Date: 2026-02-04 01:51:16
Email: haoxingjun@bytedance.com
LastEditors: haoxingjun
LastEditTime: 2026-02-04 01:52:36
Description: file information
Company: ByteDance
'''
from veadk import Agent

from intent_and_sql_tools.data_agent_tool.tool import execute_sql
from intent_and_sql_tools.data_agent_tool.visualize_tool import visualize_data
from intent_and_sql_tools.intent_tool.intent_tool import identify_intent


def create_agent() -> Agent:
    return Agent(
        name="HeQu_Data_Agent_v6_13",
        description="HeQu Data Agent",
        instruction=(
            "ALWAYS call identify_intent first. "
            "Read `next_tool` from the JSON output. "
            "Pass the ENTIRE JSON envelope to the next tool without modification."
        ),
        tools=[identify_intent, execute_sql, visualize_data],
    )


TOOLS = {
    "execute_sql": execute_sql,
    "visualize_data": visualize_data,
}


def run_query(query: str):
    envelope = identify_intent(query)
    tool = envelope.get("next_tool") or "unknown_tool"
    print(f"[Chain] identify_intent -> {tool}")
    func = TOOLS.get(tool)
    if func is None:
        return envelope
    return func(envelope)


if __name__ == "__main__":
    print(run_query("查一下土豪流失"))
    print(run_query("选出MA多头的票"))
    print(run_query("画一张最近流水趋势图"))
