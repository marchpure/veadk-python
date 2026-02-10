import json
import os
from typing import Dict, Any

# Schema definition
OVERVIEW_PARAM_V2_SCHEMA = {
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "additionalProperties": False,
  "required": ["groupId", "date", "globalFilterRule", "eventRules", "combineRules", "groupRules"],
  "properties": {
    "groupId": { "type": "string" },
    "date": {
      "type": "object",
      "properties": {
        "isDynamic": { "type": "boolean" },
        "periods": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "type": { "type": "string" },
              "last": {
                "type": "object",
                "properties": {
                  "amount": { "type": "integer" },
                  "unit": { "type": "string" }
                }
              }
            }
          }
        },
        "interval": { "type": ["integer", "null"] },
        "startTime": { "type": ["string", "null"] },
        "endTime": { "type": ["string", "null"] }
      },
      "required": ["isDynamic"]
    },
    "globalFilterRule": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "alias": { "type": ["string", "null"] },
          "mark": { "type": "string" },
          "filters": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "type": { "type": "integer" },
                "attrId": { "type": "string" },
                "operation": { "type": "string" },
                "param": {
                  "type": "object",
                  "properties": {
                    "value1": { "type": ["string", "null"] },
                    "value2": { "type": ["string", "null"] },
                    "valueArr": { "type": "array", "items": { "type": "string" } }
                  }
                }
              }
            }
          }
        }
      }
    },
    "eventRules": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "properties": {
          "mark": { "type": "string" },
          "alias": { "type": ["string", "null"] },
          "eventId": { "type": "string" },
          "type": { "type": "integer" },
          "aggregate": {
            "type": "object",
            "properties": {
              "aggregateId": { "type": "string" },
              "attrId": { "type": ["string", "null"] }
            }
          },
          "param": { "type": "object" },
          "filters": { "type": "array" },
          "op": { "type": ["string", "null"] }
        }
      }
    },
    "combineRules": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "mark": { "type": "string" },
          "expression": { "type": "string" },
          "dataType": { "type": ["integer", "string"] }
        }
      }
    },
    "groupRules": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "attrId": { "type": "string" },
          "type": { "type": "integer" },
          "groupInterval": { "type": ["string", "null"] },
          "groupType": { "type": ["string", "null"] }
        }
      }
    },
    "chartMetrics": { "type": ["array", "null"] },
    "chartGroups": { "type": ["array", "null"] },
    "limit": { "type": ["integer", "null"] }
  }
}

SYSTEM_PROMPT_TEMPLATE = """
你是一个 BI 智能问数的“参数生成器”。你的任务是：把用户的自然语言问数需求，生成一个 OverviewChart 的 V2 param JSON（将被直接存入 overview_chart.param）。
你必须只输出 JSON，不要输出解释、不要输出 markdown、不要输出任何多余文本。输出 JSON 必须严格符合下方给定的 JSON Schema（V2 Only）。

输出必须满足的硬性要求

输出必须是一个 JSON 对象，且能被 JSON.parse 成功解析。

只允许输出 Schema 中定义的字段（additionalProperties=false），不允许新增字段。

必须包含并正确填充以下必填字段：

groupId

date

globalFilterRule

eventRules（至少 1 个）

combineRules（可以为空数组）

groupRules（可以为空数组）

若用户没有明确说明时间范围，默认最近 7 天：

date.isDynamic = true

date.periods = [{ "type":"last", "last": {"amount":7,"unit":"day"} }]

date.interval 允许用整数占位（如 3），startTime/endTime 允许为 null

若用户没有任何过滤条件，仍然必须输出一个 globalFilterRule 元素（表示“全体用户”），其 filters 为空数组：

globalFilterRule = [ { "alias":"全体用户", "mark":"", "filters": [] } ]
注意：filters 允许为空数组；不要为了凑字段构造假的 filter。

对于无法确定的 ID（eventId / attrId / operation / aggregateId / aggregate.attrId 等）：

使用空字符串 "" 或 null 作为占位（按 Schema 允许的类型）。

不要输出额外的 warnings / trace 字段（Schema 不允许）。

指标与表达式规则：

每个基础指标都必须对应一个 eventRules 元素。

eventRules[i].mark 必须唯一，用 A、B、C… 递增。

combineRules 用 mark 来引用指标，例如 "A / B"、"(A - B) / B"。

combineRules[i].mark 也要唯一，例如 C、D…

派生指标/转化率/占比：

如果用户提到“转化率/占比/比率/率/人均”等，需要生成 combineRules；

若表达式引用的分子/分母指标未在用户原句明确出现，你必须自动补齐对应的 eventRules（并分配 mark）。

分组规则：

用户说“按X分组/按X和Y分组/分别看X” → groupRules 加入对应维度。

若用户说“按天/按周/按月/按小时” → groupRules 应加入“时间维度”的分组（若无法确定其 attrId，则 attrId="" 占位，type=1）。

groupInterval / groupType 可选：如无法确定可置 null。

chartMetrics/chartGroups：

如果用户提到“展示哪些指标/只看某个指标/对比多个指标”，可填 chartMetrics；否则输出空数组。

chartGroups 同理；否则输出空数组。

limit：

用户提到 TopN/排行/前20/只看前10 → 设置 limit；否则可省略或置 null（按 Schema 允许）。

语义到 V2 param 的生成方法（你必须遵守）
A. eventRules 生成

从用户问题中抽取“基础指标/事件/口径”。每个基础指标生成一个 eventRules：

mark: A/B/C...

alias: 可填中文名（如“新增用户数”），或 null

eventId: 若能确定填 ID；否则 ""

type: 1（默认事件/指标），无法确定也必须给一个整数（默认 1）

aggregate:

aggregateId: 若能确定填；否则 ""

attrId: 若聚合需要字段（sum金额）才填，否则 null

param: 可省略；如必须存在则给 {}（但 Schema 不要求）

filters: 默认 []

op: 可省略或 null

B. globalFilterRule 生成

将“全局过滤条件”（如 地区=北京、渠道=自然、端=iOS）放入 globalFilterRule[0].filters。

每个过滤生成一个 FilterRule：

type: 1（用户属性）或 2（事件属性）。无法判断默认 1。

attrId: 确定则填 ID，否则 ""

operation: 确定则填 ID，否则 ""

param: 必须是 {value1,value2,valueArr}：

等值：value1="北京"，value2=null，valueArr=[]

in：valueArr=["北京","上海"]，value1=null,value2=null

between：value1=lower,value2=upper,valueArr=[]

如果用户没有任何过滤条件：globalFilterRule = [{alias:"全体用户", mark:"", filters:[]}]

C. groupRules 生成

抽取分组维度，每个维度生成一个 GroupRuleV2：

attrId: 确定则填，否则 ""

type: 1（用户属性）或 2（事件属性），无法判断默认 1

groupInterval/groupType: 如能确定则填，否则 null

时间分组（按天/周/月/小时）也用 GroupRuleV2 表示；attrId 不确定就用 ""。

D. combineRules 生成

当用户要“转化率/占比/比率/率”，你必须生成 combineRules：

expression: 用 mark 形成表达式，例如 "A / B" 或 "A / B * 100"

dataType: 百分比推荐 3（若你们系统如此），不确定就用 "" 或 3（优先 3）

combineRules 的 mark 从未用过的字母开始（例如基础指标用了 A、B，则派生用 C）。

默认值策略（强制）

如果用户没有明确说明 groupId：groupId = ""（占位）

如果用户没有明确说明聚合方式：aggregate.aggregateId = ""（占位）

如果用户没有明确说明过滤字段的操作符：operation=""，并将值写进 param.value1/valueArr

如果用户没有说 chartType/showType/trendShow 等：不要输出这些字段（可省略）

输出格式

最终只输出一个 JSON 对象，符合 Schema。

不要输出任何注释、解释、前后缀。

JSON Schema（V2 Only）

{schema_json}
"""

def generate_bi_param(query: str) -> Dict[str, Any]:
    """
    Generates a BI OverviewChart V2 parameter JSON based on a natural language query using Volcengine Ark.
    
    Args:
        query: The user's natural language question (e.g., "Show me the daily active users for the last 7 days").
        
    Returns:
        A dictionary representing the JSON parameter.
    """
    try:
        from openai import OpenAI
    except ImportError:
        return {"error": "OpenAI library not installed. Please run `pip install openai`."}

    # 从环境变量中获取 API KEY
    api_key = os.getenv('MODEL_AGENT_API_KEY')
    if not api_key:
        return {"error": "MODEL_AGENT_API_KEY environment variable not set."}

    client = OpenAI(
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        api_key=api_key,
    )

    schema_str = json.dumps(OVERVIEW_PARAM_V2_SCHEMA, indent=2)
    system_prompt = SYSTEM_PROMPT_TEMPLATE.replace("{schema_json}", schema_str)

    try:
        # 使用 responses.create 接口 (注意：这里使用标准 Chat Completion 格式，但通过 base_url 指向 Ark)
        # 根据官方文档，Ark 兼容 OpenAI SDK
        response = client.chat.completions.create(
            model="doubao-seed-1-8-251228", # 替换为您实际可用的模型，此处使用一个常用示例，或者回退到 doubao-seed
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ],
            response_format={"type": "json_object"}, # 强制 JSON 输出
            temperature=0, # 降低随机性
            extra_body={"thinking": {"type": "disabled"}} # Disable deep thinking
        )
        
        content = response.choices[0].message.content
        if not content:
            return {"error": "Empty response from LLM"}
            
        params = json.loads(content)
        
        # Print raw response as requested
        print("\n=== Raw LLM Response (JSON) ===")
        print(json.dumps(params, indent=2, ensure_ascii=False))
        print("==============================\n")
        
        # Post-process with ParamsBackfiller
        from .fill_params import ParamsBackfiller
        backfiller = ParamsBackfiller()
        filled_params = backfiller.fill(params)
        
        return filled_params

    except Exception as e:
        return {"error": f"Failed to generate params: {str(e)}"}
