import type {
  ArtifactRevision,
  AuthoringEvent,
  PlanStep,
  TimelineState,
  ToolActivity,
  ToolCategory,
} from "./contracts";

export function createTimelineState(operationId: string): TimelineState {
  return {
    operationId,
    events: [],
    seenEventIds: new Set(),
    answerText: "",
    tools: [],
    plan: [],
    artifacts: [],
    status: operationId ? "connecting" : "idle",
  };
}

function stringValue(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function numberValue(value: unknown): number | undefined {
  const parsed = typeof value === "number"
    ? value
    : typeof value === "string" && value.trim()
      ? Number(value)
      : Number.NaN;
  return Number.isFinite(parsed) ? parsed : undefined;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function clarificationAnswer(payload: Record<string, unknown>): string | undefined {
  const questions = stringList(payload.clarification_questions);
  return questions.length > 0
    ? `需要确认以下信息：\n\n${questions.map((question) => `- ${question}`).join("\n")}`
    : undefined;
}

function toolCategory(value: unknown): ToolCategory | undefined {
  return value === "database"
      || value === "mcp"
      || value === "connector"
      || value === "retrieval"
      || value === "skill"
      || value === "artifact"
      || value === "generic"
    ? value
    : undefined;
}

export function classifyTool(name: string): ToolCategory {
  const normalized = name.toLowerCase();
  if (/(sql|database|postgres|mysql|mongo|duckdb|query)/.test(normalized)) {
    return "database";
  }
  if (/(discover|catalog|list_(?:source|resource)|connector)/.test(normalized)) {
    return "connector";
  }
  if (/(search|retrieve|knowledge|document|file|grep)/.test(normalized)) {
    return "retrieval";
  }
  if (/(skill|draft|patch|revision)/.test(normalized)) return "skill";
  if (/(html|artifact|render|dashboard)/.test(normalized)) return "artifact";
  if (/(mcp|toolset)/.test(normalized)) return "mcp";
  return "generic";
}

function recoveryHint(error: string | undefined): string | undefined {
  if (!error) return undefined;
  const normalized = error.toLowerCase();
  if (/(auth|credential|permission|forbidden|unauthorized)/.test(normalized)) {
    return "请检查连接凭证或访问权限后重试。";
  }
  if (/(timeout|timed out|network|connection)/.test(normalized)) {
    return "请检查网络与数据源状态，然后重试本轮。";
  }
  return "可重试本轮；若仍失败，请检查工具配置和输入。";
}

function toolIdentity(
  tools: ToolActivity[],
  event: AuthoringEvent,
  name: string,
): string {
  const payloadId = stringValue(event.payload.call_id)
    ?? stringValue(event.payload.callId);
  if (payloadId) return payloadId;

  // Some ADK/MCP transports omit the function-call id on the response event.
  // Pair that response with the most recent running call of the same public
  // tool instead of creating a second card.
  if (
    event.type === "tool.completed"
    || event.type === "tool.failed"
    || event.type === "tool.progress"
  ) {
    const running = [...tools].reverse().find(
      (tool) => tool.name === name && tool.status === "running",
    );
    if (running) return running.id;
  }
  const occurrence = tools.filter((tool) => tool.name === name).length + 1;
  return `tool:${name}:${occurrence}`;
}

function updateTool(
  tools: ToolActivity[],
  event: AuthoringEvent,
): ToolActivity[] {
  const payload = event.payload;
  const name = stringValue(payload.tool_name)
    ?? stringValue(payload.name)
    ?? "Tool";
  const id = toolIdentity(tools, event, name);
  const current = tools.find((tool) => tool.id === id);
  const status = event.type === "tool.failed"
    ? "failed"
    : event.type === "tool.completed"
      ? "completed"
      : "running";
  const next: ToolActivity = {
    id,
    name: current?.name ?? name,
    category:
      toolCategory(payload.tool_category)
      ?? current?.category
      ?? classifyTool(
        current?.name ?? name,
      ),
    status,
    startedAt: current?.startedAt ?? event.occurred_at,
    completedAt: status === "running" ? undefined : event.occurred_at,
    durationMs: numberValue(payload.duration_ms) ?? current?.durationMs,
    inputSummary:
      stringValue(payload.input_summary) ?? current?.inputSummary,
    outputSummary:
      stringValue(payload.output_summary) ?? current?.outputSummary,
    error: stringValue(payload.error) ?? current?.error,
    recoveryHint: recoveryHint(stringValue(payload.error) ?? current?.error),
    sessionId: event.session_id ?? current?.sessionId,
    traceId: event.trace_id ?? current?.traceId,
  };
  return [...tools.filter((tool) => tool.id !== id), next];
}

function updateArtifacts(
  artifacts: ArtifactRevision[],
  event: AuthoringEvent,
): ArtifactRevision[] {
  if (event.type !== "artifact.revision.created") return artifacts;
  const id = stringValue(event.payload.artifact_id)
    ?? stringValue(event.payload.draft_id)
    ?? event.event_id;
  const revision = numberValue(event.payload.revision);
  const next: ArtifactRevision = {
    id,
    revision,
    label: stringValue(event.payload.label)
      ?? stringValue(event.payload.display_name)
      ?? (revision ? `Skill revision ${revision}` : "Artifact revision"),
    uri: stringValue(event.payload.uri),
    ...(numberValue(event.payload.base_revision) !== undefined
      ? { baseRevision: numberValue(event.payload.base_revision) }
      : {}),
    ...(stringValue(event.payload.base_digest)
      ? { baseDigest: stringValue(event.payload.base_digest) }
      : {}),
    ...(stringValue(event.payload.new_digest)
      ? { newDigest: stringValue(event.payload.new_digest) }
      : {}),
    ...(stringValue(event.payload.view_revision_id)
      ? { viewRevisionId: stringValue(event.payload.view_revision_id) }
      : {}),
    ...(event.payload.before && typeof event.payload.before === "object"
      ? { before: event.payload.before as Record<string, unknown> }
      : {}),
    ...(event.payload.after && typeof event.payload.after === "object"
      ? { after: event.payload.after as Record<string, unknown> }
      : {}),
  };
  return [...artifacts.filter((artifact) => artifact.id !== id), next];
}

function updatePlan(plan: PlanStep[], event: AuthoringEvent): PlanStep[] {
  const rawSteps = event.payload.steps;
  if (event.type === "plan.created" && Array.isArray(rawSteps)) {
    return rawSteps.flatMap((step) => {
      if (!step || typeof step !== "object") return [];
      const value = step as Record<string, unknown>;
      const id = stringValue(value.id) ?? stringValue(value.node_id);
      if (!id) return [];
      const rawStatus = stringValue(value.status);
      const status = rawStatus === "running"
          || rawStatus === "completed"
          || rawStatus === "failed"
        ? rawStatus
        : "pending";
      return [{
        id,
        label: stringValue(value.label) ?? stringValue(value.role) ?? id,
        status,
      }];
    });
  }
  if (!event.type.startsWith("plan.step.")) return plan;
  const id = stringValue(event.payload.step_id);
  if (!id) return plan;
  const status = event.type.endsWith(".completed")
    ? "completed"
    : event.type.endsWith(".failed")
      ? "failed"
      : "running";
  return plan.map((step) => step.id === id ? { ...step, status } : step);
}

export function reduceTimelineEvent(
  state: TimelineState,
  event: AuthoringEvent,
): TimelineState {
  if (
    event.operation_id !== state.operationId ||
    state.seenEventIds.has(event.event_id) ||
    state.events.some((item) => item.sequence === event.sequence)
  ) {
    return state;
  }
  const seenEventIds = new Set(state.seenEventIds);
  seenEventIds.add(event.event_id);
  const events = [...state.events, event].sort((a, b) => a.sequence - b.sequence);
  let answerText = "";
  let finalAnswer: string | undefined;
  let tools: ToolActivity[] = [];
  let plan: PlanStep[] = [];
  let artifacts: ArtifactRevision[] = [];
  let status: TimelineState["status"] = "running";
  let warning: string | undefined;
  let error: TimelineState["error"];
  for (const item of events) {
    if (item.type === "answer.delta") {
      answerText += stringValue(item.payload.text) ?? "";
    } else if (item.type === "answer.final") {
      finalAnswer = stringValue(item.payload.text)
        ?? clarificationAnswer(item.payload)
        ?? answerText;
      answerText = finalAnswer;
    }
    if (item.type.startsWith("tool.")) tools = updateTool(tools, item);
    if (item.type.startsWith("plan.")) plan = updatePlan(plan, item);
    artifacts = updateArtifacts(artifacts, item);
    if (item.type === "operation.failed") {
      status = "failed";
      const code = stringValue(item.payload.code) ?? "RUNNER_FAILED";
      error = {
        code,
        message:
          stringValue(item.payload.message)
          ?? item.public_summary
          ?? "Agent 运行失败。",
        retryable: !/(permission|credential|validation)/i.test(code),
        kind: /(permission|credential|auth)/i.test(code)
          ? "authentication"
          : "runner",
      };
    }
    else if (
      item.type === "operation.completed"
      && item.payload.status === "awaiting_input"
    ) {
      status = "awaiting_input";
    }
    else if (item.type === "operation.cancelled") status = "cancelled";
    else if (item.terminal) status = "completed";
    if (item.type === "operation.cancelled") warning = "已停止";
  }
  const latest = events.at(-1);
  return {
    ...state,
    events,
    seenEventIds,
    lastEventId: latest?.cursor,
    answerText,
    finalAnswer,
    tools,
    plan,
    artifacts,
    status,
    warning,
    error,
  };
}
