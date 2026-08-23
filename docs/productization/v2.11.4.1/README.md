# Knowledge Workspace v2.11.4.1 Commercial GA

本目录是从 `origin/main@3dbee406d2be8eea5efe1b7fe18199a193f8f25e`
建立的 Commercial GA 合同基线。STEP 1 只定义合同、Golden Master 和测试底座，
不修改生产 TypeScript、React 或 Python 行为。

## 权威顺序

1. 冻结导出包源码、`captures.json` 与两个 route manifest。
2. 本目录中的 Commercial GA 合同。
3. 飞书产品、架构与详细设计文档。
4. 历史 Oracle 和实验实现（只读证据）。

在线 Preview、旧实现和人工记忆不能覆盖冻结导出物。所有运行数据、截图和报告只写
`/Users/bytedance/.codex/runtime/knowledge-v21141-commercial-step-1`。

## 文档

- [PRODUCT_REQUIREMENTS.md](PRODUCT_REQUIREMENTS.md)：范围、用户旅程和完成定义。
- [ARCHITECTURE.md](ARCHITECTURE.md)：Commercial 拓扑、安全和运维边界。
- [DETAILED_DESIGN.md](DETAILED_DESIGN.md)：机器合同、Golden Master 与后续实现接口。
- [EXECUTION_PROMPTS.md](EXECUTION_PROMPTS.md)：STEP 1～5 的依赖和硬门禁。

## 机器合同与测试

- `tests/fixtures/knowledge_workspace_v21141/`
  - `baseline-identity.json`
  - `source-files.json`
  - `captures.json`
  - `route-manifests.json`
  - `golden-master.json`
  - `visual-contract.json`
  - `trace-suite.json`
  - `connector-certification-matrix.json`
  - `commercial-readiness.json`
  - `performance-evidence.schema.json`
  - `e2e-skeleton.json`
  - `hotspot-guard.json`
- `tests/production_readiness/knowledge_workspace_v21141/`
  - 冻结包安全校验、identity gate、篡改负向测试和合同完整性测试。
- `tests/frontend/knowledge_workspace_v21141/`
  - Commercial E2E skeleton；STEP 1 未执行项全部显式为 `blocked`。
- `frontend/tests/knowledge-workspace-v21141/`
  - Node 自测与真实 artifact comparator；直接计算 PNG pixel mismatch、
    DOM/class/text/event/computed-style 等价、geometry delta、运行错误、a11y、
    keyboard/IME/mobile、iframe/fixture 计数和全部输入 hash。
  - `compareVisualEvidence.mjs` 提供 fail-closed CLI，将 reference/candidate
    runtime artifact 计算为 `visual-evidence.schema.json` 报告。
  - `commercial.e2e.spec.mjs` 将 13 个未实现的 Commercial E2E case 显式注册为
    Playwright skip；任何 case 被错误标记 pass 时会执行并失败，不会伪造结果。
- `frontend/knowledgeWorkspaceV21141GlobalSetup.mjs`
  - Playwright 创建 browser/page 前强制校验冻结 tar、47 文件源码树、
    readme、captures/routes/dependencies 与 13 个 capture 状态对应的 12 张 PNG。

## 当前结论

STEP 1 的结果不是 Commercial GA。所有 37 个 UI Connector 均尚无真实系统全生命周期
证据，状态为 `preview` 且 GA gate 为 `blocked`。五条产品旅程、全新安装、租户隔离、
恢复、密钥轮换和升级回滚也保持显式 blocked，后续步骤不得把合同测试替代真实
E2E。

## 基线事实

目标基线 commit 中不存在根级 `CONTEXT.md`。为遵守“缺失不臆造”的原则，本 Step
未向仓库新增一个伪基线文件；领域词汇参考了只读历史实验的 `CONTEXT.md`，最终约束
以本执行合同和冻结导出包为准。
