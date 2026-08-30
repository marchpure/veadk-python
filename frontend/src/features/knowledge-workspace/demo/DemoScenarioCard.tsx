import type { DemoScenario } from "./types";

interface Props {
  scenario: DemoScenario;
  onOpenSkill: (scenario: DemoScenario) => void;
  onViewConnection: (scenario: DemoScenario) => void;
  onRevalidate: (scenario: DemoScenario) => void;
  onCopy: (scenario: DemoScenario) => void;
}

export function DemoScenarioCard({
  scenario,
  onOpenSkill,
  onViewConnection,
  onRevalidate,
  onCopy,
}: Props) {
  const ready = scenario.status === "ready";
  return (
    <article className="kw-demo-card" data-demo-scenario={scenario.scenario_id}>
      <div className="kw-demo-card__heading">
        <div>
          <span className="kw-demo-label">示例</span>
          <h3>{scenario.title}</h3>
        </div>
        <span className={`kw-demo-status is-${scenario.status}`}>
          {ready ? "已验证" : "示例尚未初始化"}
        </span>
      </div>
      <p className="kw-demo-card__source">数据来源：{scenario.data_source || scenario.source}</p>
      <p className="kw-demo-card__skill">Skill：{scenario.skill_type}</p>
      <p className="kw-demo-card__next">{scenario.next_step}</p>
      <dl className="kw-demo-card__meta">
        <div><dt>连接</dt><dd>{scenario.connection_status}</dd></div>
        <div><dt>最后验证</dt><dd>{scenario.last_verified_at || "尚未验证"}</dd></div>
      </dl>
      <div className="kw-demo-card__actions">
        <button type="button" onClick={() => onOpenSkill(scenario)} disabled={!ready}>打开 Skill</button>
        <button type="button" onClick={() => onViewConnection(scenario)}>查看连接</button>
        <button type="button" onClick={() => onRevalidate(scenario)}>重新验证</button>
        <button type="button" onClick={() => onCopy(scenario)}>用自己的数据复制</button>
      </div>
    </article>
  );
}
