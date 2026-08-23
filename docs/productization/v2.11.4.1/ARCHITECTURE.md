# Knowledge Workspace v2.11.4.1 Commercial GA 架构

## 1. 决策

采用 Strangler 迁移。冻结导出包提供唯一前端视图，历史 Oracle 只提供后端行为证据；
生产数据和副作用逐步替换为 deep Module，不能凭 PRD 重画 UI，也不能整分支复制历史
实验实现。

```text
AgentKit Studio route/auth host
  └─ Knowledge Workspace frozen UI
       ├─ Resource Tree
       ├─ Conversation / Resource Detail
       ├─ Context Assistant / Property / Comment
       └─ Overlay / Command
                 │ versioned HTTP + durable ordered SSE
                 ▼
       Space & Access ─ Connector Catalog ─ Import Lifecycle
       Session Workspace ─ Capability Authoring
       Artifact Governance ─ Library & AgentBinding
       Action & Decision
                 │
       AgentKit Runner / Providers / Secret-KMS
                 │
       durable DB / durable queue-worker-scheduler / object storage
                 │
       logs + metrics + traces / backup + restore
```

生产 profile 是可重复构建的制品，不是开发服务器。Web/API、Worker/Scheduler 可独立
重启；状态不能依赖进程内存、浏览器、某个 PID 或某个 Codex session。

## 2. Module 责任

- Space & Access：Space 生命周期及每次操作的可信 Access Context。
- Connector Catalog：Definition、Instance、认证、发现、安全预览和连接生命周期。
- Import Lifecycle：preflight、durable Import Job、事件、取消/重试和 Indexed Revision。
- Session Workspace：Session、AssetRef 重验、分支、Agent turn 和恢复。
- Capability Authoring：Semantic/Dashboard Capability、证据、评测与发布资格。
- Artifact Governance：Revision、评论、分享、发布、版本、回滚和撤销。
- Library & AgentBinding：已授权 Published Version 的发现和不可变绑定。
- Action & Decision：Signal、Policy、Todo、Evidence、Review、Brief 和 Approval。

AgentKit Runner 不直接读写知识内部表，不接收浏览器秘密，不绕过权限，不发布可变草稿，
也不能代替人批准 Decision。

## 3. 持久化与异步

Commercial profile 必须使用 durable DB、对象存储和 durable queue/job。migration
采用版本化、幂等、expand/contract；启动检查 schema compatibility，禁止破坏性重建。

短事务使用 versioned typed HTTP。Agent turn、导入、构建、批量修复、评测和调度使用
ordered SSE：先持久化再发首事件，事件含 stream/event ID、严格递增 sequence、
timestamp、type、payload、terminal；`Last-Event-ID` 可恢复，terminal 唯一，cancel
是持久化意图。

## 4. 安全与治理

- 所有 provider I/O 前执行 tenant/Space/resource 授权。
- Secret 只以 Secret Manager/KMS 引用或密文存在，支持轮换、撤销和审计；默认/空/
  明文配置拒绝启动。
- HTML Artifact 双端 allowlist，禁止 iframe、script、事件属性、未知 URL scheme、
  外部网络和动态代码。
- PII 分类、保留期、legal hold、导出和异步可追踪删除覆盖 DB、object、index、cache。
- 审计追加式记录 actor、tenant/Space、action、resource/revision、result、request/
  idempotency ID 和时间，且不含 secret。
- rate limit、quota、并发预算、payload limit、backpressure、`429 Retry-After`、
  公平调度和 Provider circuit breaker 均为生产合同。

## 5. 健康、可观测与恢复

- startup：配置、Secret/KMS、版本与 migration 可用。
- liveness：进程事件循环健康，不把下游瞬断误判为死亡。
- readiness：DB、migration、durable queue/worker、object storage 和必需 Provider
  能力就绪；不能恒定返回 200。
- logs/metrics/traces 贯穿 request、tenant（脱敏）、session/job/artifact ID。
- SLI 覆盖 availability、HTTP/SSE、queue/worker、Connector/Provider、scheduler、
  notification、DB pool 和存储容量。
- 自动备份、完整性校验、隔离恢复和 PITR/等价机制必须实测 RPO ≤15 分钟、
  RTO ≤60 分钟。

## 6. 容量与发布

最低负载为 100 并发交互用户、20 并发 Agent turn、10 并发 Import Job。正常负载下
read API p95 ≤500ms、mutation 接受 p95 ≤1s、SSE 首事件 p95 ≤2s（外部执行时间
另计），月度可用性目标 99.9%。仓库若有更高标准，采用更高标准。

每个制品关联 source commit、依赖锁、SBOM、签名/摘要。发布采用 canary 与 rolling/
blue-green 等价策略；数据库在 expand/contract 窗口兼容旧版本，回滚不丢新写入。

## 7. 代码量与所有权

冻结前端只允许一份生产拷贝，禁止 bundle、重复 UI 和 iframe。`App.tsx` 只组合；
`service.py` 只兼容/组合；`repository.py` 只持久化；`routes.py` 只做协议映射。
这些 shared hotspot 的本 Step 行为 LOC 增长为 0。机器守卫见 `hotspot-guard.json`。
