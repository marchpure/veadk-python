import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import "./KnowledgeCenter.css";

export type KnowledgeCenterStep = "connectors" | "modeling" | "dashboard" | "evaluation";

export type KnowledgeCenterMessage =
  | { type: "veadk.knowledge-center.navigate"; step: KnowledgeCenterStep }
  | {
      type: "veadk.knowledge-center.asset-published";
      assetType: "dashboard" | "semantic_model";
      assetId: string;
      version?: string;
    }
  | { type: "veadk.knowledge-center.ready" }
  | {
      type: "veadk.knowledge-center.sync";
      step: KnowledgeCenterStep;
      theme: "light" | "dark";
      locale: "zh-CN";
    };

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; config: DataStudioConfig; origin: string }
  | { kind: "unconfigured"; message: string }
  | { kind: "unauthenticated"; message: string }
  | { kind: "unreachable"; message: string };

interface DataStudioConfig {
  configured: boolean;
  baseUrl: string;
  embedUrl: string;
  mock?: boolean;
}

export function dataStudioLoadStateFromResponse(
  response: Pick<Response, "ok" | "status">,
): LoadState | null {
  if (response.status === 409) {
    return { kind: "unconfigured", message: "服务端未配置 Data Studio 连接。" };
  }
  if (response.status === 401) {
    return { kind: "unauthenticated", message: "当前 Studio 会话未登录，请登录后访问知识中心。" };
  }
  if (!response.ok) {
    return { kind: "unreachable", message: `Byaan Data Studio 不可达（HTTP ${response.status}）。` };
  }
  return null;
}

function isStep(value: unknown): value is KnowledgeCenterStep {
  return value === "connectors" || value === "modeling" || value === "dashboard" || value === "evaluation";
}

export function isKnowledgeCenterMessageFromTrustedOrigin(
  eventOrigin: string,
  trustedOrigin: string,
  data: unknown,
): data is KnowledgeCenterMessage {
  if (!trustedOrigin || eventOrigin !== trustedOrigin) return false;
  if (!data || typeof data !== "object") return false;
  const message = data as {
    type?: unknown;
    step?: unknown;
    assetType?: unknown;
    assetId?: unknown;
    theme?: unknown;
    locale?: unknown;
  };
  if (message.type === "veadk.knowledge-center.navigate") return isStep(message.step);
  if (message.type === "veadk.knowledge-center.asset-published") {
    return (
      (message.assetType === "dashboard" || message.assetType === "semantic_model") &&
      typeof message.assetId === "string" &&
      message.assetId.trim().length > 0
    );
  }
  if (message.type === "veadk.knowledge-center.ready") return true;
  if (message.type === "veadk.knowledge-center.sync") {
    return isStep(message.step) && (message.theme === "light" || message.theme === "dark") && message.locale === "zh-CN";
  }
  return false;
}

const STEPS: Array<{ id: KnowledgeCenterStep; label: string; path: string }> = [
  { id: "connectors", label: "Connectors", path: "/sources" },
  { id: "modeling", label: "Modeling", path: "/data-models" },
  { id: "dashboard", label: "Dashboard", path: "/dashboard" },
  { id: "evaluation", label: "Evaluation", path: "/evaluation" },
];

function configOrigin(embedUrl: string): string {
  try {
    return new URL(embedUrl).origin;
  } catch {
    return "";
  }
}

function frameUrl(embedUrl: string, step: KnowledgeCenterStep): string {
  const target = STEPS.find((item) => item.id === step) ?? STEPS[0];
  return `${embedUrl.replace(/\/+$/, "")}${target.path}`;
}

async function loadConfig(): Promise<LoadState> {
  let response: Response;
  try {
    response = await fetch("/web/datastudio/config");
  } catch {
    return { kind: "unreachable", message: "无法连接 VeADK Studio 服务端，请稍后重试。" };
  }
  const error = dataStudioLoadStateFromResponse(response);
  if (error) return error;
  const config = (await response.json()) as DataStudioConfig;
  if (!config.configured || !config.embedUrl) {
    return { kind: "unconfigured", message: "未配置 Data Studio 连接。" };
  }
  const origin = configOrigin(config.embedUrl);
  if (!origin) {
    return { kind: "unreachable", message: "Data Studio 嵌入地址不是有效 URL。" };
  }
  return { kind: "ready", config, origin };
}

export function KnowledgeCenterView() {
  const [step, setStep] = useState<KnowledgeCenterStep>("connectors");
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const frameRef = useRef<HTMLIFrameElement>(null);

  const refresh = useCallback(() => {
    setState({ kind: "loading" });
    loadConfig().then(setState);
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const trustedOrigin = state.kind === "ready" ? state.origin : "";
  const src = useMemo(
    () => (state.kind === "ready" ? frameUrl(state.config.embedUrl, step) : ""),
    [state, step],
  );

  useEffect(() => {
    if (state.kind !== "ready") return;
    const message: KnowledgeCenterMessage = {
      type: "veadk.knowledge-center.sync",
      step,
      theme: "light",
      locale: "zh-CN",
    };
    frameRef.current?.contentWindow?.postMessage(message, state.origin);
  }, [state, step]);

  useEffect(() => {
    const handleMessage = (event: MessageEvent<KnowledgeCenterMessage>) => {
      if (!isKnowledgeCenterMessageFromTrustedOrigin(event.origin, trustedOrigin, event.data)) return;
      if (event.data.type === "veadk.knowledge-center.navigate") {
        setStep(event.data.step);
      }
      if (event.data.type === "veadk.knowledge-center.asset-published") {
        window.dispatchEvent(new CustomEvent("veadk:datastudio-asset-published", { detail: event.data }));
      }
    };
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [trustedOrigin]);

  return (
    <main className="kc-root">
      <header>
        <h1>Knowledge Center</h1>
        <nav aria-label="Knowledge Center flow">
          {STEPS.map((item) => (
            <button
              key={item.id}
              type="button"
              aria-current={step === item.id ? "step" : undefined}
              disabled={state.kind !== "ready"}
              onClick={() => setStep(item.id)}
            >
              {item.label}
            </button>
          ))}
        </nav>
      </header>
      {state.kind === "loading" && <p role="status">正在连接 Data Studio...</p>}
      {state.kind === "unconfigured" && <ErrorState title="未配置连接" message={state.message} onRetry={refresh} />}
      {state.kind === "unauthenticated" && <ErrorState title="未登录" message={state.message} onRetry={refresh} />}
      {state.kind === "unreachable" && <ErrorState title="Byaan 不可达" message={state.message} onRetry={refresh} />}
      {state.kind === "ready" && (
        <iframe
          ref={frameRef}
          className="kc-frame"
          src={src}
          title="Byaan Data Studio Knowledge Center"
          sandbox="allow-scripts allow-same-origin allow-forms"
        />
      )}
    </main>
  );
}

function ErrorState({
  title,
  message,
  onRetry,
}: {
  title: string;
  message: string;
  onRetry: () => void;
}) {
  return (
    <section role="status">
      <h2>{title}</h2>
      <p>{message}</p>
      <button type="button" onClick={onRetry}>
        重试
      </button>
    </section>
  );
}
