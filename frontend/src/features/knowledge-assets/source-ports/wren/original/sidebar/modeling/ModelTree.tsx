import { Braces, CircleDot, Database, Table2 } from "lucide-react";

import type { WrenOriginalModel, WrenTreeRow } from "../../types";
import { GroupTreeTitle } from "./GroupTreeTitle";

export default function ModelTree({
  models,
  selectedKeys = [],
  onOpenModelDrawer,
  onSelect,
}: {
  models: WrenOriginalModel[];
  selectedKeys?: string[];
  onOpenModelDrawer: () => void;
  onSelect: (row: WrenTreeRow) => void;
}) {
  return (
    <section className="adm-sidebar-tree adm-model-tree">
      <GroupTreeTitle title="Models" count={models.length} onAction={onOpenModelDrawer} />
      <div className="adm-tree-list">
        {models.length ? (
          models.map((model) => {
            const nodeKey = model.id;
            return (
              <div key={nodeKey} className="adm-treeNode">
                <button
                  type="button"
                  className={selectedKeys.includes(nodeKey) ? "is-selected" : ""}
                  onClick={() =>
                    onSelect({
                      id: model.id,
                      title: model.displayName,
                      detail: `${model.table} · ${model.fields.length} columns`,
                      kind: "model",
                      model,
                    })
                  }
                >
                  <Database className="kc-native-icon" />
                  <span>{model.displayName}</span>
                </button>
                <div className="adm-tree-children">
                  {[...model.fields, ...model.calculatedFields].slice(0, 12).map((field) => (
                    <button
                      type="button"
                      key={`${model.id}:${field.id}`}
                      onClick={() =>
                        onSelect({
                          id: `${model.id}:${field.id}`,
                          title: field.name,
                          detail: field.type,
                          kind: "field",
                          parentId: model.id,
                          model,
                          field,
                        })
                      }
                    >
                      {field.isPrimaryKey ? <CircleDot className="kc-native-icon" /> : <Braces className="kc-native-icon" />}
                      <span>{field.name}</span>
                    </button>
                  ))}
                  {model.relationFields.slice(0, 8).map((field) => (
                    <button
                      type="button"
                      key={`${model.id}:relation:${field.id}`}
                      onClick={() =>
                        onSelect({
                          id: `${model.id}:relation:${field.id}`,
                          title: field.name,
                          detail: "relationship",
                          kind: "field",
                          parentId: model.id,
                          model,
                          field,
                        })
                      }
                    >
                      <Table2 className="kc-native-icon" />
                      <span>{field.name}</span>
                    </button>
                  ))}
                </div>
              </div>
            );
          })
        ) : (
          <p className="adm-tree-empty">No models</p>
        )}
      </div>
    </section>
  );
}
