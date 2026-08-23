# Knowledge Workspace v2.11.4.1 详细设计

## 1. STEP 1 产物边界

本 Step 只提交文档、fixture、manifest、测试和测试配置。生产 TypeScript/React/Python
Implementation 不变。运行时下载、截图、数据库、日志和报告不入 Git。

## 2. Baseline identity gate

执行顺序固定为 URL → tar SHA-256 → archive path/link 安全 → 完整阅读
`prototype/readme.md` → source tree → captures → root route → complete route →
dependencies。任何一步失败都必须在启动截图或候选实现前退出。

源码树算法：按相对 POSIX 路径排序，对每个普通文件向同一 SHA-256 依次写入
`relative_path + NUL + raw_bytes + NUL`。行数为 LF byte 总数，冻结值 9,514；
源文件数 47，bytes 607,128。

`contract_harness.py` 提供：

- `validate-contracts`
- `verify-archive --archive ... --url ...`
- `verify-captures --capture-dir ...`

负向测试覆盖 URL、tar、源码树、两个 route、captures、dependencies、绝对路径、
`..` 穿越与 symlink 逃逸。

## 3. Provenance 与 route/capture

`source-files.json` 对每个源文件记录 source path、未来唯一 target path、SHA-256、
POSIX 行数和 bytes。STEP 2 初始移植必须逐字一致；任何 Adapter change 单独登记。

`route-manifests.json` 冻结根 manifest 的 13 个节点和完整 manifest 的 23 个节点，
每个节点记录父 route、交互、名称和 URL。`captures.json` 冻结 13 个状态、12 张唯一
PNG、URL、hash 与 1920×1080 尺寸；Dashboard 与 Alert route 共用同一 PNG 是原始
事实，动态 trace 必须另验 Alert。

## 4. Declarative Golden Master

`golden-master.json` 的 GM-01～GM-20 是唯一 trace 输入，同一对象同时驱动
`reference` 和 `candidate`，禁止候选专用宽松步骤。每项都含 route、precondition、
actions、selectors、assertions、四视口和 required evidence。
`trace-suite.json` 进一步声明同一双 driver pipeline 必须遍历 47 个 source
provenance row、13 个 capture、根 manifest 13 个节点、完整 manifest 23 个节点及
20 个 Golden Master；数量、唯一 key、JSON pointer 和 artifact 集均由 harness 校验。

比较顺序：

1. identity 与供应链。
2. DOM/class/text/event。
3. 语义、动作、URL、焦点和状态转换。
4. bounding box 与 computed style。
5. pixel diff、console/page errors、a11y。

关键 anchor 偏差 0px，其他边界 ≤1px；只排除字体抗锯齿后像素差 ≤0.1%。mask
不能覆盖业务组件。动态 GM 捕获 before/running/success/failure-or-rollback。

`visualGate.mjs` 不接受调用方填写的 `equal` 或 mismatch 数字作为事实。runner 为
reference/candidate 各写 screenshot、DOM、class、text、event、geometry、
computed-style、runtime error/isolation、a11y、keyboard、IME 与 mobile artifact；
comparator 读取原始 artifact 后计算差异与 24 个 SHA-256。Playwright `globalSetup`
要求 `KNOWLEDGE_V21141_ARCHIVE` 和 `KNOWLEDGE_V21141_CAPTURE_DIR`，并在任何
browser/page 创建前完成完整 identity 与 12 张 PNG 的 hash/dimension 校验。
`prototype/readme.md` 也固定为 SHA-256
`9c7570ba151c2f3c64a85276202450bebe217f5f1f886134b2258288bc7313d8`，
从而使“解压后先读 readme”对应的输入也可被验证，不能静默替换。
`compareVisualEvidence.mjs` 是后续 runner 的命令行入口；成功报告必须符合
`visual-evidence.schema.json`。`commercial.e2e.spec.mjs` 让本 Step 的 13 个未实现
case 在 Playwright 中保持显式 skip，而不是因没有浏览器测试文件而隐式遗漏。

## 5. Connector certification

`connector-certification-matrix.json` 从冻结 `store.ts` 的 37 个 Connector Definition
生成，包含 adapter、auth、discovery、preview、import、incremental sync、limits、
tenant isolation、last verified、evidence、owner、support tier、status 和 GA gate。

`ga-certified` 必须绑定真实系统、真实认证与当前环境 evidence；合同测试、fixture、
录制响应或静态 UI 不能升级状态。STEP 1 中所有 Connector 为 `preview`/blocked，
这准确反映尚无生产实现和真实外部环境证据。

## 6. Production interfaces

后续实现必须提供：

- versioned bootstrap/tree/command HTTP API；
- mutation 的 request context、`Idempotency-Key`、expected version 和统一脱敏错误；
- durable ordered SSE 的 resume/cancel/idempotent terminal；
- Server-derived Access Context；
- Secret/KMS reference，不向浏览器返回凭据；
- immutable Indexed Revision、Artifact Revision、Published Version 与 AgentBinding。

配置、迁移、health、RBAC、数据治理、traffic、SLI/SLO、灾备、供应链和发布合同在
`commercial-readiness.json` 中可机读。阈值不是 TODO，也没有 unknown 值。
`performance-evidence.schema.json` 是后续容量运行的可执行结果合同：100/20/10
并发下分别约束 read API、mutation accept、SSE 首事件 p95 和 99.9% availability，
缺少 production-equivalent 拓扑、制品 hash 或原始证据 hash 均不能报告 pass。

## 7. E2E 状态语义

`e2e-skeleton.json` 覆盖五条旅程、强制 Connector 集、tenant isolation、restart、
Worker crash、backup/restore、secret rotation、upgrade/rollback 和 fresh install。
STEP 1 所有 case 必须是 `blocked`；跳过测试输出不会被计为 PASS。

后续步骤只有在 evidence 是本轮真实运行、无敏感数据且可由 hash 校验时，才能将状态
改为 pass。证据缺失、过期、来自 mock/fixture 或测试范围小于要求均保持 blocked。

## 8. Harness 接入

Node 合同自测位于
`frontend/tests/knowledge-workspace-v21141/contracts.test.mjs`；Python 合同与负向测试
位于 `tests/production_readiness/knowledge_workspace_v21141/`。视觉 runner 后续必须
使用锁定 Playwright/Chromium，reference/candidate 共用浏览器、字体、locale、
timezone、DPR、seed 和 trace，并把产物写到 runtime。
