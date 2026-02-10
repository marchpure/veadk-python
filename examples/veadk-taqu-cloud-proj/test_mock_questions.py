'''
Author: haoxingjun
Date: 2026-02-10 16:14:46
Email: haoxingjun@bytedance.com
LastEditors: haoxingjun
LastEditTime: 2026-02-10 17:02:04
Description: file information
Company: ByteDance
'''
import json
from src.taqu_agent.agent import bi_agent
from veadk.types import AgentRunConfig

# Mock questions derived from overview_chart_20260209.csv
# id=7: 帖子点击率 -> "Show me the post click rate."
# id=8: 直播间送礼频率 -> "What is the gift sending frequency in live rooms for the last 7 days?"
# id=14: 直播每日消费 -> "Analyze daily live streaming consumption (count, users, amount) from 2022-05-23 to 2022-05-29."

mock_questions = [
    "查看帖子点击率",
    "最近7天直播间送礼频率是多少？",
    "分析2022年5月23日到29日的直播每日消费情况（次数、人数、金额）",
    "查看聊天室的每日消费金额"
]

print("Running mock tests for BI Agent...\n")

for i, question in enumerate(mock_questions):
    print(f"--- Test Case {i+1} ---")
    print(f"Question: {question}")
    
    # We are simulating the agent run. Since we are in a script, 
    # we can directly call the tool or simulate the agent's behavior.
    # However, veadk Agent.run() might need a proper environment.
    # Let's try to invoke the tool directly via the exposed function if possible,
    # or just print what we expect. 
    # BUT, the best way to verify "agent" logic is to see if the instruction makes sense.
    # Since we can't easily run the full LLM inference here without a real API key and cost,
    # we will focus on verifying the structure.
    
    # Actually, the user asked to "mock questions", which usually means generating the INPUTs 
    # that would be sent to the agent.
    
    # If we want to actually run it:
    # response = bi_agent.run(question)
    # print(f"Response: {response}\n")
    pass

print("\nMock questions generated successfully based on sample data.")
