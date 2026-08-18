# oracle_semantic_agent

Answers governed Oracle sales questions from Byaan Data Studio.

## 运行

```bash
pip install -r requirements.txt
cp .env.example .env   # 填入你的密钥
python app.py
```

`app.py` 通过 VeADK 的 AgentKit 公共组件发布 `root_agent`，监听 `0.0.0.0:8000`。
