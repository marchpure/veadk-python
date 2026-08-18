import { AlertCircle, Database, Play, RefreshCw } from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";

import {
  queryAskData,
  type AskDataQueryResult,
  type KnowledgeAssetMetadata,
} from "../adk/knowledgeAssets";

export function AskDataPanel({
  semanticSkills,
}: {
  semanticSkills: KnowledgeAssetMetadata[];
}) {
  const [assetId, setAssetId] = useState(semanticSkills[0]?.asset_id || "");
  const [metric, setMetric] = useState("");
  const [dimension, setDimension] = useState("");
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<AskDataQueryResult | null>(null);
  const selected = semanticSkills.find((asset) => asset.asset_id === assetId) ?? semanticSkills[0];
  const metrics = useMemo(() => valuesFrom(selected, "metrics"), [selected]);
  const dimensions = useMemo(() => valuesFrom(selected, "dimensions"), [selected]);

  if (semanticSkills.length === 0) {
    return (
      <section className="kc-native-panel kc-native-panel--slot">
        <div className="kc-native-slot-empty">
          <Database className="kc-native-state-icon" />
          <strong>需要先构建语义 Skill</strong>
          <span>AskData 只能对已发布 Semantic Skill 查询，不会直接读取原始数据源。</span>
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
      const payload = await queryAskData({
        semantic_asset_id: semanticAssetId,
        metric: metric || undefined,
        dimension: dimension || undefined,
        question: question || undefined,
        limit: 100,
      });
      setResult(payload);
    } catch (caught) {
      setError(userFacingError(caught, "AskData 查询失败，请确认语义 Skill 已发布后重试。"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="kc-native-panel kc-native-panel--slot">
      <div className="kc-native-panel-head">
        <div>
          <h2>AskData</h2>
          <span>对已发布语义能力执行受治理查询</span>
        </div>
      </div>
      <form className="kc-native-askdata-form" onSubmit={submit}>
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
          <span>指标</span>
          <select value={metric} onChange={(event) => setMetric(event.target.value)}>
            <option value="">自动选择</option>
            {metrics.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>维度</span>
          <select value={dimension} onChange={(event) => setDimension(event.target.value)}>
            <option value="">不拆分</option>
            {dimensions.map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </label>
        <label className="kc-native-askdata-question">
          <span>自然语言问题</span>
          <input
            value={question}
            placeholder="例如：按门店查看最近销售票数"
            onChange={(event) => setQuestion(event.target.value)}
          />
        </label>
        <button type="submit" disabled={busy}>
          {busy ? <RefreshCw className="kc-native-icon kc-spin" /> : <Play className="kc-native-icon" />}
          查询
        </button>
      </form>
      {error ? (
        <div className="kc-native-action-error" role="alert">
          <AlertCircle className="kc-native-icon" />
          <span>{error}</span>
        </div>
      ) : null}
      {result ? <AskDataResult result={result} /> : null}
    </section>
  );
}

function AskDataResult({ result }: { result: AskDataQueryResult }) {
  const data = result.data;
  const firstRow = data.rows[0] ?? {};
  return (
    <div className={`kc-native-askdata-result is-${result.status}`}>
      <div className="kc-native-result-grid">
        <ResultBlock title="结果" value={JSON.stringify(firstRow)} />
        <ResultBlock
          title="权限"
          value={String(data.policyDecision?.decision || result.status)}
        />
        <ResultBlock title="新鲜度" value={String(data.freshness?.status || "unknown")} />
      </div>
      <details open>
        <summary>SQL</summary>
        <pre>{data.sql || "因权限策略未执行 SQL"}</pre>
      </details>
      <details>
        <summary>指标口径</summary>
        <p>{data.metricDefinition || "未声明"}</p>
      </details>
    </div>
  );
}

function ResultBlock({ title, value }: { title: string; value: string }) {
  return (
    <div>
      <span>{title}</span>
      <strong>{value}</strong>
    </div>
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
  if (!message || /failed to fetch/i.test(message)) {
    return fallback;
  }
  return message;
}
