# Knowledge Workspace v2.11.4.1 产品需求

## 1. 产品目标

在 AgentKit Studio 的单一 Shell 中提供正式的“知识”工作区，使个人与团队能够：

1. 接入数据库、文件、网页/API 和飞书办公上下文。
2. 将来源生成可治理的 Knowledge Base、Semantic、Chart、Dashboard、
   Knowledge Graph 和 Capability。
3. 在统一且安全的 HTML Artifact Host 中查看、修改、评论、评测、分享和版本管理。
4. 将合格的不可变 Published Version 绑定到 Agent。
5. 将异常转为 Todo、Evidence、Review、Decision Brief 和人工 Approval。

“页面存在”不等于完成。生产 fixture、`localStorage`、静态成功、mock Provider 和假
SSE 均不能作为产品能力或 GA 证据。

## 2. 冻结体验

唯一前端真源是“知识资产工作区 v2.11.4.1 Final”导出包。47 个源文件、13 个 capture
状态、12 张唯一 PNG、两个 route manifest 的全部节点和 GM-01～GM-20 均受机器合同
约束。冻结事实见：

- `tests/fixtures/knowledge_workspace_v21141/baseline-identity.json`
- `tests/fixtures/knowledge_workspace_v21141/source-files.json`
- `tests/fixtures/knowledge_workspace_v21141/captures.json`
- `tests/fixtures/knowledge_workspace_v21141/route-manifests.json`
- `tests/fixtures/knowledge_workspace_v21141/golden-master.json`

Studio 只提供认证、路由前缀和挂载。冻结 `TopNav`、`FileTreePane`、主区、
`RightPane` 和 Modals 独占工作区视口，不得再叠加第二套 Knowledge Sidebar/Header。

桌面关键几何为 248px Resource Tree grid cell、`minmax(0, 1fr)` 主区、打开时 380px
右栏；树内冻结宽度为 260px。移动端目录树为左抽屉、助手为底部抽屉，任一时刻只有
一个可见输入 Composer。

## 3. 用户与授权

- 个人创作者：管理个人 Space，不能读取未授权团队资源。
- 团队成员：读取授权的 Published Version。
- 团队编辑者：发布、修复、评测和调度授权资产。
- 审批者：基于证据审批 Decision Brief。
- Agent 作者：仅绑定合格且未撤销的不可变 Published Version。

服务端 `Access Context` 是唯一授权事实。浏览器提交的 tenant、Space、owner 或 role
只表示意图，不授予权限。所有 API、SSE、缓存、队列、对象、导出、分享链接和备份恢复
都必须证明 tenant boundary。

## 4. 五条产品旅程

- J1：文件/飞书文档 → Knowledge Base → AgentBinding → 刷新恢复。
- J2：Oracle → Semantic → 团队 → Excel → Dashboard → 对话修改/分享。
- J3：网页/REST OpenAPI → Capability → 安全 HTML 报表 → 评测/分享。
- J4：金融 Capability → Dashboard → 分钟 Cron → KPI 告警 → 真实通知。
- J5：招聘异常 `+38%` → Todo/Evidence → Review 后缺口 `8（已调配 18）`
  → 六项完整 Decision Brief → 授权人批准。

旅程必须使用真实持久化、权限、外部系统、模型和通知环境。未满足时只能是 blocked。

## 5. Connector 支持边界

UI 中的每个 Connector 必须且只能处于：

- `ga-certified`：真实系统和认证下，test/discover/preview/import/refresh/recover/
  revoke/tenant-isolation 均有当前证据。
- `available-unconfigured`：真实 Implementation 存在，但当前环境未配置；UI 明确
  不可用，不能显示成功。
- `preview`：只能预览，不能描述为商业支持。
- `unsupported`：不支持。

强制 GA 集不得删除：PostgreSQL、MySQL、Oracle；CSV、Excel、JSON、
PDF/Markdown/TXT/HTML；网页抓取、REST/OpenAPI；飞书文档、Wiki、云盘、电子表格、
多维表格、妙记、会议、群聊和单聊。机器状态见
`connector-certification-matrix.json`。

## 6. 状态与质量

所有关键动作覆盖初始、加载、空、成功、部分成功、无权限、凭据过期、网络失败、超时、
取消、恢复和冲突。创建、发布、分享、调度、Todo 和审批采用幂等键；撤销或过期后
fail closed。

视觉/交互要求：

- 文案、入口、状态转换、URL、面板结果和旅程语义零缺失。
- 关键锚点精确；其他 bounding box 偏差不超过 1px。
- 仅排除字体抗锯齿后的 pixel mismatch ratio 不超过 0.1%。
- mask 仅用于光标、系统滚动条、字体抗锯齿，禁止覆盖业务组件。
- console/page error 为 0；键盘、IME、焦点、屏幕阅读器名称、对比度、
  reduced-motion 和触控目标均有门禁。

## 7. Commercial GA 完成定义

只有五条真实旅程、强制 Connector、跨租户隔离、持久化与崩溃恢复、备份恢复、
密钥轮换、升级回滚、容量/SLO、视觉/交互/a11y、安全与供应链全部有当前机器证据，
且 production 依赖图中 fixture/mock/default secret 为 0，才可宣称 Commercial GA。
