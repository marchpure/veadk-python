'''
Author: haoxingjun
Date: 2026-02-05 13:50:07
Email: haoxingjun@bytedance.com
LastEditors: haoxingjun
LastEditTime: 2026-02-06 01:29:53
Description: file information
Company: ByteDance
'''
from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from intent_and_sql_tools.intent_tool.intent_tool import identify_intent


class IntentRequest(BaseModel):
    query: str


class IntentResponse(BaseModel):
    raw_query: str
    intent: str
    prompt: str | None = None
    optimized_query: str
    error: str | None = None


app = FastAPI()


@app.get("/", response_class=HTMLResponse)
def index():
    return """
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8"/>
        <title>Intent Tool Demo</title>
        <style>
          body { font-family: Arial, sans-serif; margin: 40px; }
          .container { max-width: 720px; margin: 0 auto; }
          input[type=text] { width: 100%; padding: 10px; font-size: 16px; box-sizing: border-box; }
          button.submit-btn { margin-top: 12px; padding: 10px 16px; font-size: 16px; cursor: pointer; }
          .examples { margin-top: 20px; border-top: 1px solid #eee; padding-top: 10px; }
          .example-item { margin-bottom: 8px; cursor: pointer; color: #0066cc; text-decoration: underline; font-size: 14px; }
          .example-item:hover { color: #003366; }
          .result { margin-top: 24px; padding: 12px; border: 1px solid #ddd; border-radius: 8px; position: relative; min-height: 50px; }
          .row { margin: 6px 0; }
          .label { font-weight: bold; margin-right: 8px; }
          pre { background: #f7f7f7; padding: 10px; border-radius: 6px; white-space: pre-wrap; word-wrap: break-word; }
          .loading { display: none; text-align: center; color: #666; font-style: italic; margin-top: 10px; }
          .spinner { display: inline-block; width: 12px; height: 12px; border: 2px solid #ccc; border-top-color: #333; border-radius: 50%; animation: spin 1s linear infinite; margin-right: 5px; vertical-align: middle; }
          @keyframes spin { to { transform: rotate(360deg); } }
        </style>
      </head>
      <body>
        <div class="container">
          <h2>Intent Tool</h2>
          <div>
            <input id="q" type="text" placeholder="输入 query，如：主板30日均线上穿60日均线,站上5日均线的股票有哪些"/>
            <button class="submit-btn" onclick="run()">提交</button>
          </div>
          
          <div class="examples">
            <p><strong>示例问题 (点击自动填充并提交):</strong></p>
            <div class="example-item" onclick="fillAndRun('增量超大_超大买增量>2，均线多头，股价在5日线上，主板，非ST')">Q1: 增量超大_超大买增量>2，均线多头，股价在5日线上，主板，非ST</div>
            <div class="example-item" onclick="fillAndRun('K线实体涨幅>5%，主板，非创业板，非科创板，非ST，股价<20元')">Q2: K线实体涨幅>5%，主板，非创业板，非科创板，非ST，股价<20元</div>
            <div class="example-item" onclick="fillAndRun('券商股 + 净利润增长>0 + 市值<100亿 + 一个月涨幅<10%')">Q3: 券商股 + 净利润增长>0 + 市值<100亿 + 一个月涨幅<10%</div>
            <div class="example-item" onclick="fillAndRun('今天技术面反弹的股票有哪些')">Q4: 今天技术面反弹的股票有哪些</div>
            <div class="example-item" onclick="fillAndRun('5日乖离新高的股票有哪些')">Q5: 5日乖离新高的股票有哪些</div>
            <div class="example-item" onclick="fillAndRun('18. 前3月销额累计值同比下降(食饮)，市值<=100亿，均线多头')">Q6: 18. 前3月销额累计值同比下降(食饮)，市值<=100亿，均线多头</div>
          </div>

          <div id="loading" class="loading">
             <span class="spinner"></span> 正在解析中...
          </div>

          <div id="res" class="result" style="display:none;">
            <div class="row"><span class="label">raw_query:</span><span id="raw"></span></div>
            <div class="row"><span class="label">intent:</span><span id="intent"></span></div>
            <div class="row"><span class="label">optimized_query:</span></div>
            <pre id="opt"></pre>
          </div>
        </div>
        <script>
          function fillAndRun(text) {
            document.getElementById('q').value = text;
            run();
          }

          async function run() {
            const query = document.getElementById('q').value.trim();
            if (!query) { alert('请输入 query'); return; }

            // Show loading, hide result
            document.getElementById('loading').style.display = 'block';
            document.getElementById('res').style.display = 'none';

            try {
                const resp = await fetch('/intent', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ query })
                });
                if (!resp.ok) {
                  alert('请求失败：' + resp.status);
                  return;
                }
                const data = await resp.json();
                document.getElementById('raw').innerText = data.raw_query || '';
                document.getElementById('intent').innerText = data.intent || '';
                document.getElementById('opt').innerText = data.optimized_query || '';
                document.getElementById('res').style.display = 'block';
            } catch (e) {
                alert('请求出错: ' + e);
            } finally {
                // Hide loading
                document.getElementById('loading').style.display = 'none';
            }
          }
        </script>
      </body>
    </html>
    """


@app.post("/intent", response_model=IntentResponse)
def handle_intent(request: IntentRequest) -> IntentResponse:
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    result = identify_intent(query)
    intent = (result.get("intent") or "unknown")
    optimized_query = (result.get("optimized_query") or query)
    return IntentResponse(
        raw_query=query,
        intent=intent,
        prompt=result.get("prompt"),
        optimized_query=optimized_query,
        error=result.get("error"),
    )
