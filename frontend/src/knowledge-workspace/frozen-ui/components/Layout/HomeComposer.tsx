import { useMemo, useRef, useState, type ChangeEvent, type DragEvent, type SVGProps } from "react";
import { createRequestContext } from "../../../production/ports";
import { getServerContextRef } from "../../../production/domainClient";
import type { ResourceRef, SkillAuthoringStartPayload, TemplateRef } from "../../../production/generatedContracts";
import {
  bootstrapWorkspace,
  getFullCatalog,
  getWorkspaceAdapter,
  templateSpecStore,
} from "../../lib/store";
import { workspaceRecommendedPrompts } from "../../../production/data";
import { cn } from "../../lib/utils";

type WorkspaceScope = "personal" | "team";
type RequestedKind = NonNullable<SkillAuthoringStartPayload["requestedKind"]>;
type TemplateId =
  | "dashboard"
  | "semantic"
  | "sop"
  | "knowledge"
  | "graph_ontology"
  | "monitoring";

type TemplateCard = {
  id: TemplateId;
  label: string;
  subtitle: string;
  kind: RequestedKind;
};

type ContextChip = {
  id: string;
  name: string;
  type: string;
  revision?: string;
  source?: string;
  contextRef?: ResourceRef;
};

function ProductIcon({ children, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  );
}

function PlusIcon(props: SVGProps<SVGSVGElement>) {
  return <ProductIcon {...props}><path d="M12 5v14" /><path d="M5 12h14" /></ProductIcon>;
}

function UploadIcon(props: SVGProps<SVGSVGElement>) {
  return <ProductIcon {...props}><path d="M12 16V5" /><path d="m7 10 5-5 5 5" /><path d="M5 19h14" /></ProductIcon>;
}

function SearchIcon(props: SVGProps<SVGSVGElement>) {
  return <ProductIcon {...props}><circle cx="10.5" cy="10.5" r="5.5" /><path d="m15 15 5 5" /></ProductIcon>;
}

function TemplateIcon(props: SVGProps<SVGSVGElement>) {
  return <ProductIcon {...props}><rect x="4" y="4" width="7" height="7" rx="1.5" /><rect x="13" y="4" width="7" height="7" rx="1.5" /><rect x="4" y="13" width="7" height="7" rx="1.5" /><path d="M15 16h3" /><path d="M16.5 14.5v3" /></ProductIcon>;
}

function AgentIcon(props: SVGProps<SVGSVGElement>) {
  return <ProductIcon {...props}><path d="M12 3v3" /><rect x="5" y="7" width="14" height="10" rx="3" /><path d="M8.5 12h.01" /><path d="M15.5 12h.01" /><path d="M9 20h6" /></ProductIcon>;
}

function CloseIcon(props: SVGProps<SVGSVGElement>) {
  return <ProductIcon {...props}><path d="M6 6 18 18" /><path d="m18 6-12 12" /></ProductIcon>;
}

function ArrowIcon(props: SVGProps<SVGSVGElement>) {
  return <ProductIcon {...props}><path d="M5 12h13" /><path d="m13 6 6 6-6 6" /></ProductIcon>;
}

function DatabaseIcon(props: SVGProps<SVGSVGElement>) {
  return <ProductIcon {...props}><ellipse cx="12" cy="5" rx="7" ry="3" /><path d="M5 5v7c0 1.7 3.1 3 7 3s7-1.3 7-3V5" /><path d="M5 12v7c0 1.7 3.1 3 7 3s7-1.3 7-3v-7" /></ProductIcon>;
}

function normalizeRef(ref: unknown): ResourceRef | undefined {
  const value = ref && typeof ref === "object" ? ref as Record<string, unknown> : null;
  if (!value) return undefined;
  const kind = value.kind;
  const objectId = value.object_id ?? value.objectId;
  const revision = value.revision;
  const scope = value.scope;
  if (
    typeof kind === "string" &&
    typeof objectId === "string" &&
    typeof revision === "string" &&
    (scope === "personal" || scope === "team")
  ) {
    return {
      kind: kind as ResourceRef["kind"],
      object_id: objectId,
      revision,
      scope,
    };
  }
  return undefined;
}

function toContextChip(item: Record<string, unknown>): ContextChip {
  const resourceKind = String(item.resourceKind ?? item.type ?? item.subtype ?? "resource");
  const resourceId = String(
    item.resourceId ??
    item.assetId ??
    (resourceKind === "golden_asset" ? item.id : "") ??
    item.id ??
    "",
  );
  const id = String(item.identity ?? resourceId);
  const serverRef = normalizeRef(item.contextRef) ?? normalizeRef(getServerContextRef(resourceId));
  const revision = String(
    resourceKind === "golden_asset"
      ? item.goldenRevisionId ??
        item.golden_revision_id ??
        item.revision ??
        item.version ??
        serverRef?.revision ??
        ""
      : item.revision ??
        item.version ??
        item.goldenRevisionId ??
        item.golden_revision_id ??
        serverRef?.revision ??
        "",
  );
  return {
    id,
    name: String(item.displayName ?? item.name ?? id),
    type: resourceKind,
    revision: revision || undefined,
    source: String(item.space ?? item.scope ?? "workspace"),
    contextRef: serverRef,
  };
}

function chipToResourceRef(chip: ContextChip): ResourceRef | null {
  if (chip.contextRef) return chip.contextRef;
  if (!chip.revision) return null;
  return {
    kind: "golden_asset",
    object_id: chip.id,
    revision: chip.revision,
    scope: "personal",
  };
}

function paramsWithBuilderState(
  base: URLSearchParams,
  input: {
    prompt: string;
    template: TemplateId;
    contextChips: ContextChip[];
    scope: WorkspaceScope;
    operationId?: string;
    draftId?: string;
  },
): URLSearchParams {
  const params = new URLSearchParams(base);
  params.set("file", "skill_builder");
  params.set("request", input.prompt);
  params.set("template", input.template);
  params.set("workspace_scope", input.scope);
  params.delete("adapter");
  const contextRefs = input.contextChips
    .map((chip) => {
      const ref = chipToResourceRef(chip);
      return ref ? `${ref.kind}:${ref.object_id}:${ref.revision}:${ref.scope}` : "";
    })
    .filter(Boolean)
    .join(",");
  if (contextRefs) params.set("context_refs", contextRefs);
  else params.delete("context_refs");
  if (input.operationId) params.set("operation_id", input.operationId);
  if (input.draftId) params.set("draft_id", input.draftId);
  return params;
}

export default function HomeComposer({
  searchParams,
  setSearchParams,
}: {
  searchParams: URLSearchParams;
  setSearchParams: (params: URLSearchParams) => void;
}) {
  const isClarifyState = searchParams.get("chat") === "clarify";
  const [request, setRequest] = useState(searchParams.get("request") ?? "");
  const [contextChips, setContextChips] = useState<ContextChip[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<TemplateId>(
    (searchParams.get("template") as TemplateId | null) ?? "dashboard",
  );
  const [scope, setScope] = useState<WorkspaceScope>(
    searchParams.get("workspace_scope") === "team" ? "team" : "personal",
  );
  const [mentionQuery, setMentionQuery] = useState("");
  const [templatePanelOpen, setTemplatePanelOpen] = useState(false);
  const [sourcePickerOpen, setSourcePickerOpen] = useState(false);
  const [sourceQuery, setSourceQuery] = useState("");
  const [selectedSourceIds, setSelectedSourceIds] = useState<string[]>([]);
  const [status, setStatus] = useState<"idle" | "submitting" | "awaiting_input" | "failed" | "completed" | "cancelled">("idle");
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const catalog = getFullCatalog();
  const mentionCandidates = useMemo(() => {
    const q = mentionQuery.trim().toLowerCase();
    return catalog
      .filter((item: any) => {
        const name = String(item.displayName ?? item.name ?? "").toLowerCase();
        return q ? name.includes(q) : true;
      })
      .slice(0, 8);
  }, [catalog, mentionQuery]);

  const templateCards = useMemo<TemplateCard[]>(() => {
    const labels: Record<string, string> = {
      dashboard: "Dashboard",
      semantic: "Semantic",
      sop: "SOP",
      knowledge: "Knowledge",
      "graph-ontology": "Graph / Ontology",
      monitoring: "Monitoring",
    };
    return templateSpecStore.getState()
      .filter((spec) => spec.defaultRenderer in labels)
      .map((spec) => ({
        id: (spec.defaultRenderer === "graph_ontology"
          ? "graph_ontology"
          : spec.defaultRenderer) as TemplateId,
        label: labels[spec.templateId] ?? spec.displayName,
        subtitle: spec.scenario,
        kind: spec.capabilityIntent as RequestedKind,
      }));
  }, []);
  const selectedTemplateCard = templateCards.find((template) => template.id === selectedTemplate) ?? templateCards[0];
  const selectedTemplateSpec = templateSpecStore.getState().find(
    (spec) =>
      spec.templateId === (
        selectedTemplate === "graph_ontology" ? "graph-ontology" : selectedTemplate
      ),
  );
  const selectedTemplateRef: TemplateRef | undefined =
    selectedTemplateSpec?.templateRef;
  const canSubmit = Boolean(templateCards.length > 0 && (request.trim() || contextChips.length > 0));
  const sourceOptions = useMemo(() => {
    const resources = catalog.filter((item: any) =>
      item.resourceKind === "golden_asset" &&
      typeof (item.assetId ?? item.asset_id) === "string" &&
      typeof (item.goldenRevisionId ?? item.golden_revision_id) === "string",
    );
    const query = sourceQuery.trim().toLowerCase();
    return resources.filter((item: any) => {
      if (!query) return true;
      return String(item.displayName ?? item.name ?? "").toLowerCase().includes(query);
    });
  }, [catalog, sourceQuery]);

  const openSourcePicker = () => {
    const alreadyAdded = catalog
      .filter((item: any) => contextChips.some((chip) =>
        chip.id === String(item.assetId ?? item.asset_id ?? "") ||
        chip.id === String(item.goldenRevisionId ?? item.golden_revision_id ?? "") ||
        chip.id === String(item.id ?? ""),
      ))
      .map((item: any) => String(item.id));
    setSelectedSourceIds(alreadyAdded);
    setSourceQuery("");
    setSourcePickerOpen(true);
  };

  const closeSourcePicker = () => {
    setSourcePickerOpen(false);
    setSourceQuery("");
    setSelectedSourceIds([]);
  };

  const confirmSources = () => {
    const selected = catalog.filter((item: any) => selectedSourceIds.includes(String(item.id)));
    selected.forEach((item: any) => addChip(item));
    closeSourcePicker();
  };

  const addChip = (item: Record<string, unknown>) => {
    const chip = toContextChip(item);
    if (!chip.id) return;
    setContextChips((previous) =>
      previous.some((existing) => existing.id === chip.id)
        ? previous
        : [...previous, chip],
    );
    setMentionQuery("");
    inputRef.current?.focus();
  };

  const handleInputChange = (event: ChangeEvent<HTMLTextAreaElement>) => {
    const value = event.currentTarget.value;
    setRequest(value);
    const cursor = event.currentTarget.selectionStart;
    const beforeCursor = value.slice(0, cursor);
    const match = beforeCursor.match(/@([^\s@]*)$/);
    setMentionQuery(match ? match[1] : "");
  };

  const handleDrop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    const payload = event.dataTransfer.getData("application/json");
    if (!payload) {
      setError("上传文件需要后端导入命令；请先从“上传文件”入口完成服务端导入。");
      return;
    }
    try {
      const parsed = JSON.parse(payload);
      if (parsed && typeof parsed === "object") addChip(parsed);
    } catch {
      setError("拖入内容不是可识别的工作区资源。");
    }
  };

  const handleFileSelect = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.currentTarget.files?.[0];
    event.currentTarget.value = "";
    if (!file) return;
    setError(`已选择 ${file.name}；请通过服务端导入入口完成真实数据接入。`);
  };

  const startAuthoring = async () => {
    if (!canSubmit) {
      setError("请输入真实需求，或先引用工作区资源。");
      return;
    }
    if (!selectedTemplateRef) {
      setError("服务端尚未返回所选模板的不可变 TemplateRef，请刷新工作区后重试。");
      return;
    }
    setStatus("submitting");
    setError("");
    setMessage("等待服务端 Agent 生成 SkillDraft 与 BuildPlan…");
    if (!selectedTemplateCard) {
      setError("当前工作区尚未提供可用模板。");
      return;
    }
    const prompt = request.trim() || `基于已选上下文生成 ${selectedTemplateCard.label} Skill`;
    const resourceRefs = contextChips
      .map(chipToResourceRef)
      .filter((ref): ref is ResourceRef => Boolean(ref));
    try {
      const response = await getWorkspaceAdapter().command({
        command: "skill-authoring.start",
        payload: {
          prompt,
          requestedKind: selectedTemplateCard.kind,
          resourceRefs,
          fixedRevisions: resourceRefs.map((ref) => ref.revision),
          scope,
          displayName: prompt.slice(0, 80),
          templateRef: selectedTemplateRef,
        },
      }, createRequestContext());
      const result = response.result ?? {};
      const operation = result.operation && typeof result.operation === "object"
        ? result.operation as Record<string, unknown>
        : {};
      const draft = result.draft && typeof result.draft === "object"
        ? result.draft as Record<string, unknown>
        : {};
      const operationId = String(response.operationId ?? operation.operation_id ?? operation.operationId ?? "");
      const draftId = String(draft.draft_id ?? draft.id ?? "");
      if (!response.accepted) {
        throw new Error(String((result.error as Record<string, unknown> | undefined)?.message ?? "服务端未接受 Skill authoring 请求。"));
      }
      if (result.status === "awaiting_input") {
        setStatus("awaiting_input");
        const params = paramsWithBuilderState(searchParams, {
          prompt,
          template: selectedTemplate,
          contextChips,
          scope,
          operationId: operationId || undefined,
          draftId: draftId || undefined,
        });
        params.set("chat", "clarify");
        setSearchParams(params);
        return;
      }
      setStatus("completed");
      await bootstrapWorkspace(undefined, getWorkspaceAdapter()).catch(() => undefined);
      setSearchParams(paramsWithBuilderState(searchParams, {
        prompt,
        template: selectedTemplate,
        contextChips,
        scope,
        operationId: operationId || undefined,
        draftId: draftId || undefined,
      }));
    } catch (cause) {
      setStatus("failed");
      setError(cause instanceof Error ? cause.message : "Skill authoring 启动失败。");
    }
  };

  const statusLabel = {
    idle: "等待输入",
    submitting: "生成中",
    awaiting_input: "等待输入",
    failed: "失败，可重试",
    completed: "完成，等待 Builder 恢复",
    cancelled: "已取消",
  }[status];

  return (
    <main
      className="flex h-full min-h-0 flex-col bg-white"
      onDragOver={(event) => event.preventDefault()}
      onDrop={handleDrop}
    >
      <section className="mx-auto flex w-full max-w-5xl flex-1 flex-col px-6 py-6 md:px-8 md:py-10">
        <div className="hidden items-center justify-center gap-3 pb-7 text-sm font-semibold text-slate-700 md:flex">
          {["选择数据与上下文", "选择模板", "生成 Skill", "调试并发布"].map((label, index) => (
            <div key={label} className="flex items-center gap-3">
              <span className="flex h-6 w-6 items-center justify-center rounded-full border border-slate-200 bg-slate-50 text-xs text-slate-500">{index + 1}</span>
              <span>{label}</span>
              {index < 3 && <ArrowIcon className="h-4 w-4 text-slate-300" />}
            </div>
          ))}
        </div>

        <div className="flex flex-1 flex-col">
          <section className={cn(
            "flex min-h-0 flex-1 -translate-y-[4px] flex-col items-center justify-center",
            isClarifyState ? "md:translate-y-[14px]" : "md:translate-y-[1px]",
          )}>
            <div className="w-full max-w-[704px]">
              <div className="mb-6 text-center">
                <h1 className="mx-auto w-fit max-w-full text-left text-3xl font-bold tracking-tight text-slate-900">今天想解决什么业务问题？</h1>
                <p className="mx-auto mt-3 max-w-[327px] text-sm leading-5 text-slate-500">
                  输入问题或拖入上下文，AI 将自动匹配模板生成 Skill
                </p>
              </div>

              <div className="mt-10 w-full rounded-2xl border border-slate-200 bg-white shadow-lg shadow-slate-200/50 transition-all focus-within:border-blue-500 focus-within:ring-2 focus-within:ring-blue-100 md:mt-[36px]">
                {contextChips.length > 0 && (
                  <div className="flex flex-wrap gap-2 px-4 pt-4">
                    {contextChips.map((chip) => (
                      <div key={chip.id} className="group flex max-w-full items-center rounded-lg border border-blue-100 bg-blue-50 px-2.5 py-1.5 text-xs font-medium text-blue-800">
                        <span className="truncate">{chip.name}</span>
                        <span className="ml-1.5 rounded bg-white px-1 text-[10px] text-blue-500" title={`来源: ${chip.source ?? "workspace"} · revision: ${chip.revision ?? "等待服务端返回"}`}>
                          来源 / revision
                        </span>
                        <button
                          type="button"
                          aria-label={`移除上下文 ${chip.name}`}
                          onClick={() => setContextChips((previous) => previous.filter((item) => item.id !== chip.id))}
                          className="ml-2 rounded text-blue-400 opacity-70 outline-none hover:text-red-500 focus:ring-2 focus:ring-blue-500 group-hover:opacity-100"
                        >
                          <CloseIcon className="h-3 w-3" />
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                <div className="relative">
                  <textarea
                    ref={inputRef}
                    aria-label="描述要构建的 Skill"
                    value={request}
                    onChange={handleInputChange}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                        event.preventDefault();
                        void startAuthoring();
                      }
                    }}
                    placeholder="描述目标，或输入 @ 搜索并引用真实工作区资源…"
                    rows={2}
                    className="block min-h-[80px] w-full resize-none border-0 bg-transparent px-4 py-4 text-base leading-6 text-slate-800 outline-none placeholder:text-slate-300 md:min-h-[95px] md:py-4 md:leading-7"
                    disabled={status === "submitting"}
                  />
                  {mentionQuery !== "" && (
                    <div className="absolute bottom-full left-4 z-20 mb-2 w-72 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-xl">
                      <div className="flex items-center border-b border-slate-100 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-500">
                        <SearchIcon className="mr-1.5 h-3.5 w-3.5" /> @ 搜索资源
                      </div>
                      <div className="max-h-56 overflow-y-auto p-1">
                        {mentionCandidates.length > 0 ? mentionCandidates.map((item: any) => (
                          <button
                            key={String(item.identity ?? item.id)}
                            type="button"
                            onClick={() => addChip(item)}
                            className="flex w-full items-center rounded-lg px-3 py-2 text-left outline-none hover:bg-blue-50 focus:bg-blue-50"
                          >
                            <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-700">{String(item.displayName ?? item.name ?? item.id)}</span>
                            <span className="ml-2 shrink-0 text-[10px] text-slate-400">{String(item.resourceKind ?? item.type ?? "resource")}</span>
                          </button>
                        )) : (
                          <div className="px-3 py-4 text-center text-xs text-slate-400">等待服务端 bootstrap 返回匹配资源</div>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                <div className="flex flex-row items-center justify-between gap-0 border-t border-slate-100 bg-slate-50/70 px-3 py-3 md:gap-3 md:py-3">
                      <div className="flex flex-nowrap items-center gap-2">
                    <button
                      type="button"
                      onClick={openSourcePicker}
                      aria-haspopup="dialog"
                      aria-expanded={sourcePickerOpen}
                      className="inline-flex h-[58px] w-[100px] items-center rounded-lg border border-slate-200 bg-white px-2.5 py-0 text-sm font-medium text-slate-600 outline-none hover:bg-slate-50 focus:ring-2 focus:ring-blue-500 md:h-auto md:w-auto md:py-2"
                    >
                      <DatabaseIcon className="mr-1.5 h-4 w-4" /> 接入数据源
                    </button>
                    <label
                      title="通过服务端导入真实数据文件"
                      className="inline-flex h-[58px] w-[100px] cursor-pointer items-center rounded-lg border border-slate-200 bg-white px-2.5 py-0 text-sm font-medium text-slate-600 outline-none hover:bg-slate-50 focus-within:ring-2 focus-within:ring-blue-500 md:h-auto md:w-auto md:py-2"
                    >
                      <UploadIcon className="mr-1.5 h-4 w-4" /> 上传文件
                      <input
                        type="file"
                        className="sr-only"
                        accept=".csv,.md,.txt,.xlsx"
                        onChange={handleFileSelect}
                      />
                    </label>
                    <button
                      type="button"
                      onClick={() => setTemplatePanelOpen((value) => !value)}
                      aria-expanded={templatePanelOpen}
                      className="inline-flex h-[58px] w-[86px] items-center rounded-lg border border-slate-200 bg-white px-2.5 py-0 text-sm font-medium text-slate-600 outline-none hover:bg-slate-50 focus:ring-2 focus:ring-blue-500 md:h-auto md:w-auto md:py-2"
                    >
                      <TemplateIcon className="mr-1.5 h-4 w-4" /> 模板库
                    </button>
                  </div>
                      <div className="flex items-center gap-0 md:gap-3">
                    {status !== "idle" && (
                      <span className="text-xs text-slate-500" aria-live="polite">{statusLabel}</span>
                    )}
                    {status === "submitting" && (
                      <button
                        type="button"
                        onClick={() => {
                          setStatus("cancelled");
                          setMessage("已取消本地提交；未写入任何成功状态。");
                        }}
                        className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-500 outline-none hover:bg-slate-50 focus:ring-2 focus:ring-blue-500"
                      >
                        取消
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => void startAuthoring()}
                      disabled={!canSubmit || status === "submitting"}
                        className="inline-flex h-[56px] w-[121px] items-center rounded-lg bg-blue-600 px-5 py-0 text-sm font-bold text-white shadow-sm outline-none hover:bg-blue-700 focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:bg-slate-300 md:h-auto md:w-auto md:py-2"
                    >
                      {status === "submitting" ? "生成中…" : "生成 Skill"}
                      <ArrowIcon className="ml-1.5 h-4 w-4" />
                    </button>
                  </div>
                </div>
              </div>

              {workspaceRecommendedPrompts.length > 0 && (
                    <div className={cn(
                      "mt-8 flex flex-wrap justify-center gap-2",
                      isClarifyState ? "md:mt-[32px]" : "md:mt-[14px]",
                    )} aria-label="推荐问题">
                  {workspaceRecommendedPrompts.slice(0, 3).map((item) => (
                    <button
                      key={item.id}
                      type="button"
                      onClick={() => {
                        setRequest(item.prompt);
                        inputRef.current?.focus();
                      }}
                      className="max-w-full truncate rounded-full border border-slate-200 bg-slate-50/80 px-4 py-2 text-xs font-medium text-slate-500 shadow-sm outline-none hover:border-blue-300 hover:bg-slate-100 hover:text-slate-700 focus:ring-2 focus:ring-blue-500"
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
              )}

              {(error || message) && (
                <div className={error ? "mt-4 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" : "mt-4 rounded-xl border border-blue-100 bg-blue-50 px-4 py-3 text-sm text-blue-700"} role={error ? "alert" : "status"}>
                  {error || message}
                  {status === "failed" && (
                    <button type="button" onClick={() => void startAuthoring()} className="ml-3 font-semibold underline underline-offset-2">重试</button>
                  )}
                </div>
              )}
            </div>
          </section>

          {sourcePickerOpen && (
            <div
              className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-900/30 p-4 backdrop-blur-[1px]"
              role="dialog"
              aria-modal="true"
              aria-label="接入数据源"
              onMouseDown={(event) => {
                if (event.target === event.currentTarget) closeSourcePicker();
              }}
            >
              <div className="flex max-h-[min(680px,calc(100vh-32px))] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
                <div className="flex items-start justify-between border-b border-slate-100 bg-slate-50 px-5 py-4">
                  <div>
                    <h2 className="text-base font-semibold text-slate-900">接入数据源</h2>
                    <p className="mt-1 text-xs text-slate-500">可同时选择多个真实工作区数据源，确认后一起用于生成 Skill。</p>
                  </div>
                  <button type="button" aria-label="关闭数据源选择" onClick={closeSourcePicker} className="rounded-lg p-1.5 text-slate-400 outline-none hover:bg-slate-200 focus:ring-2 focus:ring-blue-500">
                    <CloseIcon className="h-5 w-5" />
                  </button>
                </div>
                <div className="border-b border-slate-100 p-4">
                  <input
                    value={sourceQuery}
                    onChange={(event) => setSourceQuery(event.currentTarget.value)}
                    aria-label="搜索数据源"
                    placeholder="搜索数据源"
                    className="w-full rounded-xl border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                  />
                </div>
                <div className="min-h-0 flex-1 overflow-y-auto p-3">
                  {sourceOptions.length === 0 ? (
                    <div className="rounded-xl border border-dashed border-slate-200 px-4 py-10 text-center text-sm text-slate-500">
                      暂无可用数据源，请先通过真实连接器完成接入。
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {sourceOptions.map((item: any) => {
                        const id = String(item.id);
                        const checked = selectedSourceIds.includes(id);
                        return (
                          <label key={id} className={cn(
                            "flex cursor-pointer items-center gap-3 rounded-xl border px-3 py-3 transition-colors",
                            checked ? "border-blue-300 bg-blue-50/60" : "border-slate-200 bg-white hover:border-blue-200 hover:bg-slate-50",
                          )}>
                            <input
                              type="checkbox"
                              checked={checked}
                              onChange={(event) => {
                                const isChecked = event.currentTarget.checked;
                                setSelectedSourceIds((previous) =>
                                  isChecked
                                    ? previous.includes(id) ? previous : [...previous, id]
                                    : previous.filter((value) => value !== id),
                                );
                              }}
                              className="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                            />
                            <DatabaseIcon className="h-5 w-5 shrink-0 text-blue-600" />
                            <span className="min-w-0 flex-1">
                              <span className="block truncate text-sm font-medium text-slate-800">{String(item.displayName ?? item.name ?? id)}</span>
                              <span className="mt-0.5 block truncate font-mono text-[10px] text-slate-400">{String(item.goldenRevisionId ?? item.golden_revision_id)}</span>
                            </span>
                          </label>
                        );
                      })}
                    </div>
                  )}
                </div>
                <div className="flex shrink-0 items-center justify-between gap-3 border-t border-slate-100 bg-slate-50 px-4 py-3">
                  <span className="text-xs text-slate-500" aria-live="polite">已选择 {selectedSourceIds.length} 个数据源</span>
                  <div className="flex gap-2">
                    <button type="button" onClick={closeSourcePicker} className="rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-600 outline-none hover:bg-slate-50 focus:ring-2 focus:ring-blue-500">取消</button>
                    <button type="button" onClick={confirmSources} disabled={selectedSourceIds.length === 0} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white outline-none hover:bg-blue-700 focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:bg-slate-300">加入上下文</button>
                  </div>
                </div>
              </div>
            </div>
          )}

          {templatePanelOpen && (
          <div
            className="fixed inset-0 z-[80] flex items-center justify-center bg-slate-900/30 p-4 backdrop-blur-[1px]"
            role="dialog"
            aria-modal="true"
            aria-label="模板库"
            onClick={(event) => {
              if (event.target === event.currentTarget) setTemplatePanelOpen(false);
            }}
          >
          <aside className="flex max-h-[min(720px,calc(100vh-40px))] w-full max-w-xl flex-col gap-4 overflow-y-auto rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl">
            <div>
              <div className="mb-2 flex items-center justify-between">
                <h2 className="text-sm font-bold text-slate-900">模板库</h2>
                <button
                  type="button"
                  aria-label="关闭模板库"
                  onClick={() => setTemplatePanelOpen(false)}
                  className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
                >
                  <CloseIcon className="h-4 w-4" />
                </button>
              </div>
              <div className="grid gap-2 sm:grid-cols-2">
                {templateCards.map((template) => (
                  <button
                    key={template.id}
                    type="button"
                    onClick={() => {
                      setSelectedTemplate(template.id);
                      setTemplatePanelOpen(false);
                    }}
                    className={`rounded-xl border p-3 text-left outline-none focus:ring-2 focus:ring-blue-500 ${
                      selectedTemplate === template.id ? "border-blue-300 bg-blue-50 shadow-sm" : "border-slate-200 bg-white hover:bg-slate-50"
                    }`}
                  >
                    <span className="text-sm font-semibold text-slate-800">{template.label}</span>
                    <p className="mt-1 text-xs leading-5 text-slate-500">{template.subtitle}</p>
                  </button>
                ))}
              </div>
            </div>

            <div className="rounded-xl border border-blue-100 bg-blue-50 p-3">
              <div className="flex items-center text-sm font-bold text-blue-900">
                <AgentIcon className="mr-2 h-4 w-4" /> Agent 推荐模板
              </div>
              <p className="mt-2 text-xs leading-5 text-blue-800">
                当前按你的目标和真实上下文生成建议，由分析助手协助确认后创建能力。
              </p>
            </div>

            <button
              type="button"
              onClick={() => {
                const params = new URLSearchParams(searchParams);
                params.set("file", "add_data");
                setSearchParams(params);
              }}
              className="inline-flex items-center justify-center rounded-xl border border-slate-200 bg-white px-4 py-3 text-sm font-semibold text-slate-700 outline-none hover:bg-slate-50 focus:ring-2 focus:ring-blue-500"
            >
              <PlusIcon className="mr-2 h-4 w-4" /> 添加真实数据连接 / MCP
            </button>
          </aside>
          </div>
          )}
        </div>
      </section>
    </main>
  );
}
