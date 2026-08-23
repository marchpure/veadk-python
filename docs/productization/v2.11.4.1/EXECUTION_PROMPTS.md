# Knowledge Workspace v2.11.4.1 Commercial 执行合同

## 阶段图

```text
STEP 1 contracts / Golden Master
             │
STEP 2 single Shell / frozen UI / production Adapter boundary
             │
      ┌──────┼──────┬──────┐
      3A     3B     3C     3D
 connector session action platform
      └──────┴──────┴──────┘
             │
STEP 4 serial integration / Commercial RC
             │
STEP 5 clean-environment independent GA verification
```

依赖只通过 commit、tag、机器合同和 evidence manifest 传递，不通过 PID、运行 session
或未提交工作区传递。Oracle 和历史实验 worktree 始终只读。

## STEP 1

从精确 `origin/main@3dbee406d2be8eea5efe1b7fe18199a193f8f25e` 建立
`feat/knowledge-v21141-commercial-ga`。只写产品化文档与测试目录；下载和运行证据
写 runtime。先校验冻结供应链并读 readme，再生成 identity/provenance/route/capture/
GM/Connector/Commercial/E2E/hotspot 合同。提交
`test(knowledge): define v2.11.4.1 commercial ga contracts`，tag
`knowledge-v2.11.4.1-commercial-step-1`，不 push。

## STEP 2

仅从 STEP 1 tag 开始。逐字移植 47 个源文件为唯一生产 UI，再在独立 host/Adapter
边界做构建适配。Studio 仅做 route/auth mount，不能叠第二 Shell。production graph
不得触达 fixture、localStorage persistence、mock Provider、static success 或 fake
SSE。用 STEP 1 同一 trace 执行两个 manifest、13 captures、GM-01～20 × 四视口。

## STEP 3A：Space、Connector、Import

从 STEP 2 tag 建独立 worktree。实现 tenant/Space、RBAC、真实 Connector、Secret/KMS、
durable Import Job、Indexed Revision 与 Knowledge Base。对强制 Connector 逐项取真实
证据；缺环境保持 blocked。

## STEP 3B：Session、Capability、Artifact

从 STEP 2 tag 建独立 worktree。实现 durable Session/AssetRef、AgentKit Runner、
ordered SSE、Capability、safe HTML Artifact、Revision/Published Version/
AgentBinding。不得复制 Runner 或创建平行 UI。

## STEP 3C：Action、Evaluation、Scheduler

从 STEP 2 tag 建独立 worktree。实现 Evaluation、Signal/Todo/Evidence/Review/
Decision Brief/人类 Approval、durable scheduler、KPI alert 与真实通知。必须覆盖
Worker crash、DST、重复触发和部分失败。

## STEP 3D：Commercial Platform

从 STEP 2 tag 建独立 worktree。实现 production image/topology、config/probes、
observability、rate/quota/backpressure、tenant isolation、KMS、PII/retention/delete/
export、backup/restore、容量、SBOM/license/security 和 release/rollback。

## STEP 4

只有 3A～3D tags 与 evidence 完整时，按 3A→3B→3C→3D 串行集成。production-like
环境使用真实 DB、object storage、KMS、模型、Connector 和通知，执行所有旅程、视觉、
安全、性能、恢复和供应链门禁。任何硬门禁失败不得创建 RC tag。

## STEP 5

从 RC 在完全独立、空白环境重建不可变制品，重新执行安装/升级、强制 Connector、
J1～J5、视觉/a11y、100/20/10 容量、2 小时稳定性、安全、PITR、rollback 和告警
Runbook。只有 `ga-evidence.json` 对每个要求都有本轮机器证据且所有硬门禁通过，才可
创建 Commercial GA tag；否则明确 blocked。

## 全阶段不变量

- 不降低阈值，不扩大 mask，不替换冻结基线。
- 不以 mock、fixture、旧截图或旧报告替代真实 E2E。
- 不提交 tar、bundle、notebook、截图、DB、log、PID 或运行产物。
- 不使用 iframe，不让浏览器持有秘密。
- 不把领域编排堆入 `App.tsx`、`service.py`、`repository.py` 或 `routes.py`。
- 不 push，不切生产流量；外部发布需要单独授权。
