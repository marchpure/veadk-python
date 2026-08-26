import type { ToolActivity } from "./contracts";
import { ChevronIcon, StatusIcon, ToolTypeIcon } from "./icons";

const CATEGORY_LABELS: Record<ToolActivity["category"], string> = {
  database: "数据库 / SQL",
  mcp: "MCP 调用",
  connector: "连接器发现",
  retrieval: "文件与知识检索",
  skill: "Skill 修改",
  artifact: "HTML Artifact",
  generic: "工具调用",
};

export function ToolCallCard({ tool }: { tool: ToolActivity }) {
  const isCode = tool.category === "database"
    || /```|select\b|with\b/i.test(tool.inputSummary ?? "");
  return (
    <details className={`agent-tool agent-tool--${tool.status}`}>
      <summary>
        <ToolTypeIcon category={tool.category} className="agent-icon" />
        <span className="agent-tool__heading">
          <span className="agent-tool__kind">{CATEGORY_LABELS[tool.category]}</span>
          <span className="agent-tool__name">{tool.name}</span>
        </span>
        <span className="agent-tool__status" data-status={tool.status}>
          <StatusIcon className="agent-icon" />
          {tool.status === "running"
            ? "运行中"
            : tool.status === "completed"
              ? "已完成"
              : "失败"}
        </span>
        {tool.durationMs !== undefined && (
          <span className="agent-tool__duration">{tool.durationMs} ms</span>
        )}
        <ChevronIcon className="agent-chevron" />
      </summary>
      <div className="agent-tool__detail">
        {tool.inputSummary && (
          <div>
            <span>输入</span>
            {isCode
              ? <pre><code>{tool.inputSummary}</code></pre>
              : <p>{tool.inputSummary}</p>}
          </div>
        )}
        {tool.outputSummary && (
          <div><span>结果</span><p>{tool.outputSummary}</p></div>
        )}
        {tool.error && (
          <div className="agent-tool__error">
            <span>失败原因</span>
            <p>{tool.error}</p>
            {tool.recoveryHint && <p>{tool.recoveryHint}</p>}
          </div>
        )}
      </div>
    </details>
  );
}
