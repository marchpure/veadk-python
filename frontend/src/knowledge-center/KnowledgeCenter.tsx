import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  Database,
  Loader2,
  LogIn,
  Network,
  RefreshCw,
  ShieldAlert,
  SlidersHorizontal,
} from "lucide-react";
import "./KnowledgeCenter.css";

export type KnowledgeCenterStep = "connectors" | "modeling" | "dashboard" | "evaluation";

export type KnowledgeCenterMessage =
  | {
      type: "veadk.knowledge-center.navigate";
      step: KnowledgeCenterStep;
    }
  | {
      type: "veadk.knowledge-center.asset-published";
      assetType: "dashboard" | "semantic_model";
      assetId: string;
      version?: string;
    }
  | {
      type: "veadk.knowledge-center.ready";
    }
  | {
      type: "veadk.knowledge-center.sync";
      step: KnowledgeCenterStep;
      theme: "light" | "dark";
      locale: "zh-CN";
    };

interface DataStudioConfig {
  configured: boolean;
  baseUrl: string;
  embedUrl: string;
  mock?: boolean;
}

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; config: DataStudioConfig; origin: string }
  | { kind: "unconfigured"; message: string }
  | { kind: "unauthenticated"; message: string }
  | { kind: "unreachable"; message: string };

export function dataStudioLoadStateFromResponse(
  response: Pick<Response, "ok" | "status">,
): LoadState | null {
  if (response.status === 409) {
    return {
      kind: "unconfigured",
      message: "服务端未配置 Data Studio 连接。",
    };
  }
  if (response.status === 401) {
    return {
      kind: "unauthenticated",
      message: "当前 Studio 会话未登录，请登录后访问知识中心。",
    };
  }
  if (!response.ok) {
    return {
      kind: "unreachable",
      message: `Byaan Data Studio 不可达（HTTP ${response.status}）。`,
    };
  }
  return null;
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
  const isStep = (value: unknown): value is KnowledgeCenterStep =>
    value === "connectors" ||
    value === "modeling" ||
    value === "dashboard" ||
    value === "evaluation";
  if (message.type === "veadk.knowledge-center.navigate") {
    return isStep(message.step);
  }
  if (message.type === "veadk.knowledge-center.asset-published") {
    return (
      (message.assetType === "dashboard" || message.assetType === "semantic_model") &&
      typeof message.assetId === "string" &&
      message.assetId.trim().length > 0
    );
  }
  if (message.type === "veadk.knowledge-center.ready") {
    return true;
  }
  if (message.type === "veadk.knowledge-center.sync") {
    return (
      isStep(message.step) &&
      (message.theme === "light" || message.theme === "dark") &&
      message.locale === "zh-CN"
    );
  }
  return false;
}

const STEPS: Array<{
  id: KnowledgeCenterStep;
  label: string;
  path: string;
  icon: typeof Database;
}> = [
  { id: "connectors", label: "连接器", path: "/sources", icon: Network },
  { id: "modeling", label: "建模", path: "/data-models", icon: Database },
  { id: "dashboard", label: "看板", path: "/dashboard", icon: BarChart3 },
  { id: "evaluation", label: "评测分享", path: "/evaluation", icon: SlidersHorizontal },
];

function configOrigin(embedUrl: string): string {
  try {
    return new URL(embedUrl).origin;
  } catch {
    return "";
  }
}

function frameUrl(embedUrl: string, step: KnowledgeCenterStep): string {
  const base = embedUrl.replace(/\/+$/, "");
  const targetStep = STEPS.find((item) => item.id === step) ?? STEPS[0];
  return `${base}${targetStep.path}`;
}

async function loadConfig(): Promise<LoadState> {
  let response: Response;
  try {
    response = await fetch("/web/datastudio/config");
  } catch {
    return {
      kind: "unreachable",
      message: "无法连接 VeADK Studio 服务端，请稍后重试。",
    };
  }
  const errorState = dataStudioLoadStateFromResponse(response);
  if (errorState) return errorState;
  const config = (await response.json()) as DataStudioConfig;
  if (!config.configured || !config.embedUrl) {
    return {
      kind: "unconfigured",
      message: "未配置 Data Studio 连接。",
    };
  }
  const origin = configOrigin(config.embedUrl);
  if (!origin) {
    return {
      kind: "unreachable",
      message: "Data Studio 嵌入地址不是有效 URL。",
    };
  }
  return { kind: "ready", config, origin };
}

function EmptyState({
  icon: Icon,
  title,
  message,
  action,
}: {
  icon: typeof AlertTriangle;
  title: string;
  message: string;
  action?: () => void;
}) {
  return (
    <div className="kc-empty" role="status">
      <Icon className="kc-empty-icon" aria-hidden />
      <h2>{title}</h2>
      <p>{message}</p>
      {action && (
        <button type="button" className="kc-action" onClick={action}>
          <RefreshCw className="kc-i" />
          重试
        </button>
      )}
    </div>
  );
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
      if (
        !isKnowledgeCenterMessageFromTrustedOrigin(
          event.origin,
          trustedOrigin,
          event.data,
        )
      ) {
        return;
      }
      const data = event.data;
      if (data.type === "veadk.knowledge-center.navigate") {
        setStep(data.step);
      }
      if (data.type === "veadk.knowledge-center.asset-published") {
        window.dispatchEvent(
          new CustomEvent("veadk:datastudio-asset-published", { detail: data }),
        );
      }
    };
    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [trustedOrigin]);

  return (
    <div className="kc-root">
      <header className="kc-header">
        <div className="kc-title-block">
          <span className="kc-product-mark">KC</span>
          <div>
            <h1>知识中心</h1>
            <p>连接器、建模、看板、评测分享由 Byaan Data Studio 承载</p>
          </div>
        </div>
        <nav className="kc-step-nav" aria-label="知识中心流程">
          {STEPS.map(({ id, label, icon: Icon }, index) => (
            <button
              key={id}
              type="button"
              className={step === id ? "is-active" : ""}
              aria-current={step === id ? "step" : undefined}
              onClick={() => setStep(id)}
              disabled={state.kind !== "ready"}
            >
              <span className="kc-step-index">{index + 1}</span>
              <Icon className="kc-i" aria-hidden />
              <span>{label}</span>
            </button>
          ))}
        </nav>
      </header>

      <main className="kc-main">
        {state.kind === "loading" && (
          <div className="kc-loading" role="status">
            <Loader2 className="kc-i kc-spin" />
            正在连接 Data Studio…
          </div>
        )}
        {state.kind === "unconfigured" && (
          <EmptyState
            icon={ShieldAlert}
            title="未配置连接"
            message={state.message}
            action={refresh}
          />
        )}
        {state.kind === "unauthenticated" && (
          <EmptyState icon={LogIn} title="未登录" message={state.message} action={refresh} />
        )}
        {state.kind === "unreachable" && (
          <EmptyState
            icon={AlertTriangle}
            title="Byaan 不可达"
            message={state.message}
            action={refresh}
          />
        )}
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
    </div>
  );
}
