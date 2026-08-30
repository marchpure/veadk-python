import { useState, type ReactNode } from "react";
import type { ConversationTurnModel } from "../assistant/assistant-model";
import type {
  Artifact,
  AuthoringSession,
  ConnectionProfile,
  Draft,
  Revision,
  WorkspaceResource,
} from "../domain/types";
import { ArtifactWorkspace } from "./ArtifactWorkspace";
import { SkillConversation } from "./SkillConversation";

export function SkillWorkspaceShell({
  draft,
  revisions,
  artifacts,
  connections,
  resources,
  sessions,
  currentSession,
  composerValue,
  turns,
  busy,
  published,
  modeSelectorSlot,
  hasArtifact,
  artifactPaneSlot,
  onOpenDataTools,
  onUpdateContext,
  onCreateSession,
  onSelectSession,
  onRefreshSession,
  onComposerDraftChange,
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
  sessions: AuthoringSession[];
  currentSession: AuthoringSession | null;
  composerValue: string;
  turns: ConversationTurnModel[];
  busy: string;
  published: boolean;
  modeSelectorSlot?: ReactNode;
  hasArtifact?: boolean;
  artifactPaneSlot?: ReactNode;
  onOpenDataTools: () => void;
  onUpdateContext: (connectionIds: string[], resourceIds: string[]) => Promise<void>;
  onCreateSession: () => Promise<void>;
  onSelectSession: (authoringSessionId: string) => void;
  onRefreshSession: () => Promise<void>;
  onComposerDraftChange: (value: string) => void;
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
  const [mobileDrawer, setMobileDrawer] = useState<"artifacts" | null>(null);
  const title = revisions.at(-1)?.skill_name || draft.goal;
  const boundConnections = connections.filter((item) => draft.connection_ids.includes(item.connection_id));
  const boundResources = resources.filter((item) => draft.resource_ids.includes(item.resource_id));
  const showArtifactPane = hasArtifact ?? artifacts.length > 0;
  return (
    <section className={`kw-skill-workshop${showArtifactPane ? " has-artifact" : " is-conversation-only"}`}>
      <SkillConversation
        title={title}
        turns={turns}
        connections={boundConnections}
        resources={boundResources}
        sessions={sessions}
        currentSession={currentSession}
        composerValue={composerValue}
        busy={busy === "message" || busy === "retry" || busy === "cancel"}
        modeSelectorSlot={modeSelectorSlot}
        hasArtifacts={showArtifactPane}
        onOpenArtifacts={showArtifactPane ? () => setMobileDrawer("artifacts") : undefined}
        onOpenDataTools={onOpenDataTools}
        onCreateSession={onCreateSession}
        onSelectSession={(id) => {
          onSelectSession(id);
        }}
        onRefreshSession={onRefreshSession}
        onComposerDraftChange={onComposerDraftChange}
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
      {showArtifactPane ? (
        <div
          className={mobileDrawer === "artifacts" ? "kw-workshop-mobile-drawer is-open" : "kw-workshop-artifacts"}
          data-w2-slot="artifact-pane"
        >
          {artifactPaneSlot || (
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
          )}
        </div>
      ) : null}
    </section>
  );
}
