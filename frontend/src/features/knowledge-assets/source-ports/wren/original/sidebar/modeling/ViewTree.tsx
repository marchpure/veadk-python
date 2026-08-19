import { Braces, Table2 } from "lucide-react";

import type { WrenOriginalView, WrenTreeRow } from "../../types";
import { GroupTreeTitle } from "./GroupTreeTitle";

export default function ViewTree({
  views,
  selectedKeys = [],
  onSelect,
}: {
  views: WrenOriginalView[];
  selectedKeys?: string[];
  onSelect: (row: WrenTreeRow) => void;
}) {
  return (
    <section className="adm-sidebar-tree adm-view-tree">
      <GroupTreeTitle title="Views" count={views.length} onAction={() => undefined} />
      <div className="adm-tree-list">
        {views.length ? (
          views.map((view) => (
            <div key={view.id} className="adm-treeNode">
              <button
                type="button"
                className={selectedKeys.includes(view.id) ? "is-selected" : ""}
                onClick={() =>
                  onSelect({
                    id: view.id,
                    title: view.displayName,
                    detail: `${view.table} · ${view.fields.length} columns`,
                    kind: "view",
                    model: view,
                  })
                }
              >
                <Table2 className="kc-native-icon" />
                <span>{view.displayName}</span>
              </button>
              <div className="adm-tree-children">
                {view.fields.slice(0, 12).map((field) => (
                  <button
                    type="button"
                    key={`${view.id}:${field.id}`}
                    onClick={() =>
                      onSelect({
                        id: `${view.id}:${field.id}`,
                        title: field.name,
                        detail: field.type,
                        kind: "field",
                        parentId: view.id,
                        model: view,
                        field,
                      })
                    }
                  >
                    <Braces className="kc-native-icon" />
                    <span>{field.name}</span>
                  </button>
                ))}
              </div>
            </div>
          ))
        ) : (
          <p className="adm-tree-empty">No views</p>
        )}
      </div>
    </section>
  );
}
