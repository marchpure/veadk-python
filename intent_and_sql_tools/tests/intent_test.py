'''
Author: haoxingjun
Date: 2026-02-04 02:36:47
Email: haoxingjun@bytedance.com
LastEditors: haoxingjun
LastEditTime: 2026-02-04 02:37:59
Description: file information
Company: ByteDance
'''
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from intent_and_sql_tools.intent_tool.intent_tool import identify_intent


def main():
    cases = [
        "查一下土豪流失",
        "选出MA多头的票",
        "画一张最近流水趋势图",
    ]
    for query in cases:
        envelope = identify_intent(query)
        print({"query": query, "envelope": envelope})


if __name__ == "__main__":
    main()
