import { AlertCircle, BarChart3, CheckCircle2, RefreshCw, Wand2 } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import {
  buildDashboardSkill,
  type DashboardSkillBuildResult,
  type KnowledgeAssetMetadata,
  type KnowledgeAssetSpace,
} from "../adk/knowledgeAssets";

export function DashboardBuildPanel({
  activeSpace,
  semanticSkills,
  onBuilt,
}: {
  activeSpace: KnowledgeAssetSpace | null;
  semanticSkills: KnowledgeAssetMetadata[];
  onBuilt: () => Promise<void> | void;
}) {
  const [assetId, setAssetId] = useState(semanticSkills[0]?.asset_id || "");
  const [name, setName] = useState("语义指标看板");
  const [intent, setIntent] = useState("展示核心指标、维度拆解和策略证据");
  const [metric, setMetric] = useState("");
  const [dimension, setDimension] = useState("");
  const [publish, setPublish] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<DashboardSkillBuildResult | null>(null);
  const selected = semanticSkills.find((asset) => asset.asset_id === assetId) ?? semanticSkills[0];
  const metrics = useMemo(() => valuesFrom(selected, "metrics"), [selected]);
  const dimensions = useMemo(() => valuesFrom(selected, "dimensions"), [selected]);

  if (semanticSkills.length === 0) {
    return (
      <section className="kc-native-panel kc-native-panel--slot">
        <div className="kc-native-slot-empty">
          <BarChart3 className="kc-native-state-icon" />
          <strong>需要先构建语义 Skill</strong>
          <span>Dashboard Skill 只能从已发布 Semantic Skill 和 AskData 证据生成。</span>
        </div>
      </section>
    );
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const semanticAssetId = assetId || selected?.asset_id;
    if (!semanticAssetId) {
      setError("请选择一个已发布 Semantic Skill。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const payload = await buildDashboardSkill({
        space_id: activeSpace?.id,
        semantic_asset_id: semanticAssetId,
        name,
        intent,
        metric: metric || undefined,
        dimensions: dimension ? [dimension] : [],
        publish,
      });
      await onBuilt();
      setResult(payload);
    } catch (caught) {
      setError(userFacingError(caught, "生成 Dashboard Skill 失败，请确认语义能力可查询后重试。"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="kc-native-panel kc-native-panel--slot">
      <div className="kc-native-panel-head">
        <div>
          <h2>Dashboard Skill 生成</h2>
          <span>从 AskData 证据生成可被 Agent 选择的看板能力</span>
        </div>
      </div>
      <form className="kc-native-dashboard-form" onSubmit={submit}>
        <label>
          <span>Semantic Skill</span>
          <select value={assetId} onChange={(event) => setAssetId(event.target.value)}>
            {semanticSkills.map((asset) => (
              <option key={asset.asset_id} value={asset.asset_id}>
                {asset.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>看板名称</span>
          <input required value={name} onChange={(event) => setName(event.target.value)} />
        </label>
        <label className="kc-native-dashboard-intent">
          <span>生成意图</span>
          <input value={intent} onChange={(event) => setIntent(event.target.value)} />
        </label>
        <label>
          <span>种子指标</span>
          <select value={metric} onChange={(event) => setMetric(event.target.value)}>
            <option value="">自动选择</option>
            {metrics.map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </select>
        </label>
        <label>
          <span>拆解维度</span>
          <select value={dimension} onChange={(event) => setDimension(event.target.value)}>
            <option value="">不拆分</option>
            {dimensions.map((value) => (
              <option key={value} value={value}>{value}</option>
            ))}
          </select>
        </label>
        <label className="kc-native-checkbox">
          <input
            type="checkbox"
            checked={publish}
            onChange={(event) => setPublish(event.target.checked)}
          />
          <span>生成后发布到 Agent 能力选择器</span>
        </label>
        <button type="submit" disabled={busy}>
          {busy ? <RefreshCw className="kc-native-icon kc-spin" /> : <Wand2 className="kc-native-icon" />}
          生成 Dashboard Skill
        </button>
      </form>
      {error ? (
        <div className="kc-native-action-error" role="alert">
          <AlertCircle className="kc-native-icon" />
          <span>{error}</span>
        </div>
      ) : null}
      {result ? (
        <div className="kc-native-dashboard-preview">
          <header>
            <CheckCircle2 className="kc-native-icon" />
            <strong>{result.dashboard.name}</strong>
            <span>{result.status === "succeeded" ? "已生成" : result.status}</span>
          </header>
          <p>{result.dashboard.publish_state === "published" ? "已发布到 Agent 能力选择器。" : "已保存为草稿。"}</p>
          <small>Agent 创建页现在可以选择这个 Dashboard Skill。</small>
        </div>
      ) : null}
    </section>
  );
}

function valuesFrom(asset: KnowledgeAssetMetadata | undefined, key: "metrics" | "dimensions"): string[] {
  const values = asset?.capabilities?.[key];
  if (Array.isArray(values)) return values.map(String).filter(Boolean);
  const mdlValues = asset?.capability_package?.mdl;
  if (mdlValues && typeof mdlValues === "object") {
    const items = (mdlValues as Record<string, unknown>)[key];
    if (Array.isArray(items)) {
      return items
        .map((item) =>
          item && typeof item === "object"
            ? String((item as Record<string, unknown>).id || "")
            : String(item || ""),
        )
        .filter(Boolean);
    }
  }
  return [];
}

function userFacingError(error: unknown, fallback: string): string {
  const message = error instanceof Error ? error.message : "";
  if (!message || /failed to fetch/i.test(message)) return fallback;
  return message;
}
