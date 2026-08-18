import { useEffect, useMemo, useState } from "react";
import { Database, ExternalLink, Loader2 } from "lucide-react";

import "./KnowledgeCenter.css";

interface DataStudioConfig {
  configured: boolean;
  embedUrl: string;
  origin: string;
  mock?: boolean;
}

interface DataStudioFrameMessage {
  source?: string;
  type?: string;
}

type KnowledgeCenterState =
  | { status: "loading" }
  | { status: "ready"; config: DataStudioConfig }
  | { status: "error"; message: string };

async function loadConfig(): Promise<DataStudioConfig> {
  const response = await fetch("/web/datastudio/config", {
    headers: { accept: "application/json" },
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    const detail =
      typeof payload?.detail === "string"
        ? payload.detail
        : "Data Studio 连接未配置或不可达。";
    throw new Error(detail);
  }
  return response.json() as Promise<DataStudioConfig>;
}

export function KnowledgeCenterView() {
  const [state, setState] = useState<KnowledgeCenterState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    loadConfig()
      .then((config) => {
        if (!cancelled) setState({ status: "ready", config });
      })
      .catch((error) => {
        if (!cancelled) {
          setState({
            status: "error",
            message: error instanceof Error ? error.message : "加载知识资产中心失败。",
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const iframeUrl = useMemo(() => {
    if (state.status !== "ready" || !state.config.configured) return "";
    const url = new URL(state.config.embedUrl);
    url.pathname = "/embedded/knowledge-center";
    url.searchParams.set("embedded", "veadk-studio");
    return url.toString();
  }, [state]);

  useEffect(() => {
    if (state.status !== "ready" || !state.config.configured) return;

    const allowedOrigin = state.config.origin;
    const handleMessage = (event: MessageEvent<DataStudioFrameMessage>) => {
      if (event.origin !== allowedOrigin) return;
      if (event.data?.source !== "byaan-datastudio") return;
      if (!event.data.type?.startsWith("datastudio:")) return;
    };

    window.addEventListener("message", handleMessage);
    return () => window.removeEventListener("message", handleMessage);
  }, [state]);

  return (
    <main className="kc-page">
      {state.status === "loading" ? (
        <div className="kc-state" role="status">
          <Loader2 className="kc-icon kc-spin" />
          正在加载知识资产中心…
        </div>
      ) : state.status === "error" ? (
        <div className="kc-state" role="alert">
          <Database className="kc-icon" />
          <span>{state.message}</span>
        </div>
      ) : !state.config.configured ? (
        <div className="kc-state kc-state--empty" role="status">
          <Database className="kc-icon" />
          <div className="kc-empty-copy">
            <strong>未发现本机 Data Studio</strong>
            <span>知识资产中心会自动连接当前机器上运行的 BYAAN Data Studio。</span>
            <span>请确认 BYAAN backend 和 frontend 已启动，然后刷新本页。</span>
          </div>
        </div>
      ) : (
        <>
          <div className="kc-toolbar">
            <a
              className="kc-open"
              href={state.config.embedUrl}
              target="_blank"
              rel="noreferrer"
            >
              <ExternalLink className="kc-icon" />
              打开 Data Studio
            </a>
          </div>
          <iframe
            className="kc-frame"
            title="Byaan Data Studio Knowledge Center"
            src={iframeUrl}
            sandbox="allow-forms allow-scripts allow-same-origin allow-popups"
            referrerPolicy="no-referrer"
          />
        </>
      )}
    </main>
  );
}
