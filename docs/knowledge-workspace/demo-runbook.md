# Knowledge Workshop Commercial W5 Demo Runbook

W5 的 Demo Tenant 默认关闭。普通租户不会因为安装了代码而看到示例对象：

```bash
export KNOWLEDGE_DEMO_ENABLED=true
export KNOWLEDGE_DEMO_SEED_VERSION=w5-v1
export KNOWLEDGE_DEMO_STATE_DB=.veadk/knowledge-demo.sqlite3
docker compose -f demo-services/docker-compose.yml up -d
docker compose -f demo-services/docker-compose.yml ps
```

四个本地 provider 都必须是 healthy：PostgreSQL `15432`、售后 Web Action `18081`、巡检 Form API `18082`、MCP `18083`。MCP provider 实现标准 Streamable HTTP `initialize`、发现和 `tools/call`，可由 Connection Service 真实 discover/invoke。provider 健康本身不代表完整 Demo 已初始化。

显式 seed 入口要求一个真实 gate module：

```bash
python tools/seed_demo_tenant.py \
  --tenant demo-tenant \
  --workspace demo-workspace \
  --principal demo-principal \
  --gate-module your_integration.demo_gate
```

`--gate-module` 由 Integration 在 W1–W4 合并后提供；W5 不内置或替代 AutoSkill/OpenViking lifecycle runner。未提供 gate、依赖不可用或任一真实校验失败时，seed 必须 fail closed。

`gate(scenario)` 必须对每条 scenario 完成：

1. Connection Service `validate` + `discover`；
2. Connection Service invocation-bound `lease`；
3. PostgreSQL 执行只读 query，或 Web/Form/MCP 执行真实 invoke；
4. OpenViking 可用时读取历史案例知识；
5. AutoSkill 真实 create/generate、`validate_skill`、revision、artifact HTML、publish。

gate 返回 `connection_status=verified` 和 `skill_status=generated` 之前，seed 不会写入 ready 状态。缺少 AutoSkill/OpenViking 或任一步失败时，前端显示“示例尚未初始化”及下一步，而不会导入 fixture 冒充成功。

重复执行 `(tenant_id, workspace_id, seed_version)` 返回同一组记录；升级 seed version 会创建新的、可审计的 seed 记录。只清理指定 demo tenant/workspace/version：

```bash
curl -X POST http://127.0.0.1:8000/api/knowledge/v1/demo/reset \
  -H 'content-type: application/json' \
  -d '{"seed_version":"w5-v1"}'
```

Oracle 只在连接配置界面作为“需用户凭据”的示例；无凭据时必须保持未连接。

Integration 在五路合并后将 `DemoBootstrap` 挂到 Knowledge Workspace landing surface；W5 不修改主入口。挂载依据见 `demo/wiring-manifest.json`。
