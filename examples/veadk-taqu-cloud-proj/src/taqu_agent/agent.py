'''
Author: haoxingjun
Date: 2026-02-10 16:03:47
Email: haoxingjun@bytedance.com
LastEditors: haoxingjun
LastEditTime: 2026-02-10 16:57:06
Description: file information
Company: ByteDance
'''
from veadk import Agent
from .tools import generate_bi_param

# Define the BI Agent
bi_agent = Agent(
    name="bi_param_generator",
    description="An intelligent agent that converts natural language queries into BI system parameters.",
    instruction="""
    You are a BI Parameter Generator Agent.
    Your sole responsibility is to take a user's natural language question about data analysis
    and convert it into a structured JSON parameter object using the `generate_bi_param` tool.
    
    When a user asks a question like "Show me DAU for the last week" or "Analyze retention by channel",
    you MUST call `generate_bi_param` with their exact query.
    
    CRITICAL:
    1. You MUST return the JSON object returned by the `generate_bi_param` tool.
    2. You MUST wrap the JSON output in a Markdown code block, like this:
    ```json
    { ... }
    ```
    3. The JSON inside the code block MUST be pretty-printed with indentation (e.g. 2 spaces) for better readability. Do NOT output a single-line minified JSON string.
    4. Do NOT add any conversational text, explanations, or summaries before or after the Markdown block.
    """,
    tools=[generate_bi_param],
    model_extra_config={"extra_body": {"thinking": {"type": "disabled"}}}
)

root_agent = bi_agent
