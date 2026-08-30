import { useCallback, useEffect, useState } from "react";
import { withAuth } from "../../../adk/auth";
import { withLocalUser } from "../../../adk/identity";
import { DemoOnboarding } from "./DemoOnboarding";
import { DemoScenarioCard } from "./DemoScenarioCard";
import type { DemoManifest, DemoScenario } from "./types";
import "./demo.css";

const MANIFEST_URL = "/api/knowledge/v1/demo/manifest";

export interface DemoBootstrapProps {
  manifestUrl?: string;
  onOpenSkill?: (scenario: DemoScenario) => void | Promise<void>;
  onViewConnection?: (scenario: DemoScenario) => void | Promise<void>;
  onCopy?: (scenario: DemoScenario) => void | Promise<void>;
  onRevalidate?: (scenario: DemoScenario) => void | Promise<void>;
}

export function DemoBootstrap({
  manifestUrl = MANIFEST_URL,
  onOpenSkill = () => undefined,
  onViewConnection = () => undefined,
  onCopy = () => undefined,
  onRevalidate = () => undefined,
}: DemoBootstrapProps) {
  const [manifest, setManifest] = useState<DemoManifest | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    setError("");
    try {
      const response = await fetch(withAuth(manifestUrl), {
        headers: withLocalUser({ Accept: "application/json" }),
      });
      if (!response.ok) throw new Error(`manifest HTTP ${response.status}`);
      const payload = await response.json() as { data?: DemoManifest };
      if (!payload.data) throw new Error("manifest 缺少 data");
      setManifest(payload.data);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "示例状态读取失败");
    }
  }, [manifestUrl]);
  useEffect(() => { void load(); }, [load]);

  if (error) {
    return <section className="kw-demo-shell kw-demo-error" role="alert"><h2>示例暂时不可用</h2><p>{error}</p><button type="button" onClick={() => void load()}>重试</button></section>;
  }
  if (!manifest) return <section className="kw-demo-shell" aria-busy="true">正在读取示例状态…</section>;
  if (!manifest.enabled) return null;
  const hasReady = manifest.scenarios.some((scenario) => scenario.status === "ready");
  return (
    <section className="kw-demo-shell" data-demo-status={manifest.status}>
      <header className="kw-demo-shell__header">
        <div><span className="kw-demo-kicker">Knowledge Workshop · Demo Tenant</span><h1>真实示例工作台</h1><p>所有卡片均为示例数据，和生产数据隔离。未通过真实连接验证的内容不会显示为已连接。</p></div>
        <span className="kw-demo-tenant-badge">示例租户 · {manifest.seed_version || "未初始化"}</span>
      </header>
      {!hasReady && <DemoOnboarding nextStep={manifest.next_step} />}
      <div className="kw-demo-grid">
        {manifest.scenarios.map((scenario) => <DemoScenarioCard key={scenario.scenario_id} scenario={scenario} onOpenSkill={onOpenSkill} onViewConnection={onViewConnection} onRevalidate={async (item) => { await onRevalidate(item); await load(); }} onCopy={onCopy} />)}
      </div>
    </section>
  );
}
