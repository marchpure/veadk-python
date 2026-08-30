# Knowledge Workshop Commercial W5 Demo Runbook

W5 的 Demo Tenant 默认关闭。普通租户不会因为安装了代码而看到示例对象：

```bash
tools/start_knowledge_commercial_demo.sh
```

脚本先检查端口，不会停止其它 Session；默认启动 Studio BFF `8000`、Frontend
`5173`、Connection Service `38200`、AutoSkill `38202`、PostgreSQL `25432`
以及三个本地 provider `18081`–`18083`。如需启动 OpenViking，设置
`KNOWLEDGE_DEMO_OPENVIKING_COMMAND`。端口和 checkout 均可通过同名前缀环境变量覆盖。

启动后以本地用户显式 seed：

```bash
curl -X POST \
  -H 'X-VeADK-Local-User: tester' \
  http://127.0.0.1:8000/api/knowledge/v1/demo/seed
```

PostgreSQL 主场景只有在 validate、discover、invocation-bound lease、真实查询、
AutoSkill create/validate、freeze、HTML run 和 publish 全部通过后才显示 ready。
另外两个 P1 场景在完整生命周期未接通时保持 blocked。

显式 seed 入口要求一个真实 gate module：

```bash
python tools/seed_demo_tenant.py \
  --tenant demo-tenant \
  --workspace demo-workspace \
  --principal demo-principal \
  --gate-module your_integration.demo_gate
```

`--gate-module` 由 Integration 在 W1–W4 合并后提供；W5 不内置或替代 AutoSkill/OpenViking lifecycle runner。未提供 gate、依赖不可用或任一真实校验失败时，seed 必须 fail closed。

`gate(scenario)` 对 ready scenario 必须完成：

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
