import { GitBranch, Search, ShieldCheck, Table2 } from "lucide-react";

import type { WrenOriginalDiagram, WrenTreeRow } from "../types";
import ModelTree from "./modeling/ModelTree";
import ViewTree from "./modeling/ViewTree";
import { GroupTreeTitle } from "./modeling/GroupTreeTitle";

export default function Modeling({
  data,
  query,
  onQueryChange,
  onOpenModelDrawer,
  onOpenRelationshipDrawer,
  onOpenMetricDrawer,
  onSelect,
  semanticRows,
  relationshipRows,
  metricRows,
}: {
  data: WrenOriginalDiagram;
  query: string;
  onQueryChange: (value: string) => void;
  onOpenModelDrawer: () => void;
  onOpenRelationshipDrawer: () => void;
  onOpenMetricDrawer: () => void;
  onSelect: (row: WrenTreeRow) => void;
  semanticRows: WrenTreeRow[];
  relationshipRows: WrenTreeRow[];
  metricRows: WrenTreeRow[];
}) {
  const lowerQuery = query.trim().toLowerCase();
  const filter = <T extends WrenTreeRow>(rows: T[]) =>
    lowerQuery ? rows.filter((row) => `${row.title} ${row.detail}`.toLowerCase().includes(lowerQuery)) : rows;

  return (
    <aside className="kc-wren-sidebar adm-modeling-sidebar">
      <label className="adm-sidebar-search">
        <Search className="kc-native-icon" />
        <input value={query} placeholder="Search model, field, metric" onChange={(event) => onQueryChange(event.target.value)} />
      </label>
      <section className="adm-sidebar-tree adm-semantic-tree">
        <GroupTreeTitle title="Semantic Skills" count={semanticRows.length} />
        <div className="adm-tree-list">
          {filter(semanticRows).map((row) => (
            <button type="button" key={row.id} className="adm-treeNode" onClick={() => onSelect(row)}>
              <ShieldCheck className="kc-native-icon" />
              <span>{row.title}</span>
              <em>{row.detail}</em>
            </button>
          ))}
        </div>
      </section>
      <ModelTree models={data.models} selectedKeys={[]} onOpenModelDrawer={onOpenModelDrawer} onSelect={onSelect} />
      <ViewTree views={data.views} selectedKeys={[]} onSelect={onSelect} />
      <section className="adm-sidebar-tree adm-relationship-tree">
        <GroupTreeTitle title="Relationships" count={relationshipRows.length} onAction={onOpenRelationshipDrawer} />
        <div className="adm-tree-list">
          {filter(relationshipRows).map((row) => (
            <button type="button" key={row.id} className="adm-treeNode" onClick={() => onSelect(row)}>
              <GitBranch className="kc-native-icon" />
              <span>{row.title}</span>
              <em>{row.detail}</em>
            </button>
          ))}
        </div>
      </section>
      <section className="adm-sidebar-tree adm-metric-tree">
        <GroupTreeTitle title="Metrics" count={metricRows.length} onAction={onOpenMetricDrawer} />
        <div className="adm-tree-list">
          {filter(metricRows).map((row) => (
            <button type="button" key={row.id} className="adm-treeNode" onClick={() => onSelect(row)}>
              <Table2 className="kc-native-icon" />
              <span>{row.title}</span>
              <em>{row.detail}</em>
            </button>
          ))}
        </div>
      </section>
    </aside>
  );
}
