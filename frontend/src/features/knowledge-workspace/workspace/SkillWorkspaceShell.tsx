import { useState } from "react";
import type { ConversationTurnModel } from "../assistant/assistant-model";
import type {
  Artifact,
  ConnectionProfile,
  Draft,
  Revision,
  WorkspaceResource,
} from "../domain/types";
import { ArtifactWorkspace } from "./ArtifactWorkspace";
import { InvocationRail } from "./InvocationRail";
import { SkillConversation } from "./SkillConversation";

export function SkillWorkspaceShell({
  draft,
  revisions,
  artifacts,
  connections,
  resources,
  turns,
  busy,
  published,
  onOpenDataTools,
  onUpdateContext,
  onSend,
  onRun,
  onCancel,
  onReconnect,
  onRetry,
  onShare,
  onPublish,
  onBindAgent,
  onAdvanced,
}: {
  draft: Draft;
  revisions: Revision[];
  artifacts: Artifact[];
  connections: ConnectionProfile[];
  resources: WorkspaceResource[];
  turns: ConversationTurnModel[];
  busy: string;
  published: boolean;
  onOpenDataTools: () => void;
  onUpdateContext: (connectionIds: string[], resourceIds: string[]) => Promise<void>;
  onSend: (message: string, intent: "update" | "run") => Promise<void>;
  onRun: (message: string) => Promise<void>;
  onCancel: () => Promise<void>;
  onReconnect: (turn: ConversationTurnModel) => void;
  onRetry: (turn: ConversationTurnModel) => void;
  onShare: () => void;
  onPublish: () => void;
  onBindAgent: () => void;
  onAdvanced: () => void;
}) {
  const [mobileDrawer, setMobileDrawer] = useState<"invocations" | "artifacts" | null>(null);
  const [focusInvocationId, setFocusInvocationId] = useState<string>();
  const title = revisions.at(-1)?.skill_name || draft.goal;
  const boundConnections = connections.filter((item) => draft.connection_ids.includes(item.connection_id));
  const boundResources = resources.filter((item) => draft.resource_ids.includes(item.resource_id));
  return (
    <section className="kw-skill-workshop">
      <div className={mobileDrawer === "invocations" ? "kw-workshop-mobile-drawer is-open" : "kw-workshop-rail"}>
        <InvocationRail
          turns={turns}
          activeInvocationId={focusInvocationId}
          onSelect={(id) => {
            setFocusInvocationId(id);
            setMobileDrawer(null);
          }}
          onClose={mobileDrawer ? () => setMobileDrawer(null) : undefined}
        />
      </div>
      <SkillConversation
        title={title}
        turns={turns}
        connections={boundConnections}
        resources={boundResources}
        busy={busy === "message" || busy === "retry" || busy === "cancel"}
        focusInvocationId={focusInvocationId}
        onOpenInvocations={() => setMobileDrawer("invocations")}
        onOpenArtifacts={() => setMobileDrawer("artifacts")}
        onOpenDataTools={onOpenDataTools}
        onRemoveConnection={(id) => void onUpdateContext(
          draft.connection_ids.filter((item) => item !== id),
          draft.resource_ids,
        ).catch(() => undefined)}
        onRemoveResource={(id) => void onUpdateContext(
          draft.connection_ids,
          draft.resource_ids.filter((item) => item !== id),
        ).catch(() => undefined)}
        onSend={onSend}
        onRun={onRun}
        onCancel={onCancel}
        onReconnect={onReconnect}
        onRetry={onRetry}
      />
      <div className={mobileDrawer === "artifacts" ? "kw-workshop-mobile-drawer is-open" : "kw-workshop-artifacts"}>
        <ArtifactWorkspace
          artifacts={artifacts}
          revisions={revisions}
          turns={turns}
          published={published}
          onClose={mobileDrawer ? () => setMobileDrawer(null) : undefined}
          onShare={onShare}
          onPublish={onPublish}
          onBindAgent={onBindAgent}
          onAdvanced={onAdvanced}
        />
      </div>
    </section>
  );
}
