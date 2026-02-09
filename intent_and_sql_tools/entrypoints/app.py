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

from intent_and_sql_tools.intent_tool.intent_tool import identify_intent


def create_agent() -> Agent:
    return Agent(
        name="HeQu_Intent_Agent",
        description="HeQu Intent Agent",
        instruction=(
            "ALWAYS call identify_intent first. "
            "Read `next_tool` from the JSON output. "
            "Pass the ENTIRE JSON envelope to the next tool without modification."
        ),
        tools=[identify_intent],
    )


def run_query(query: str):
    envelope = identify_intent(query)
    print("[Chain] identify_intent")
    return envelope


if __name__ == "__main__":
    print(run_query("查一下土豪流失"))
    print(run_query("选出MA多头的票"))
    print(run_query("画一张最近流水趋势图"))
