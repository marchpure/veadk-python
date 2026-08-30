import type { ComponentType } from "react";
import type {
  KnowledgeSourceAction,
  KnowledgeSourceExtension,
  KnowledgeSourceOption,
} from "./knowledge-source-contracts";
import type { KnowledgeSourceRef } from "../features/knowledge-workspace/domain/types";

export type {
  KnowledgeSourceAction,
  KnowledgeSourceOption,
} from "./knowledge-source-contracts";

type KnowledgeSourcePublicModule = {
  knowledgeSourceExtension?: KnowledgeSourceExtension;
  loadOpenVikingWorkspace?: () => Promise<OpenVikingWorkspaceModule>;
};

type OpenVikingWorkspaceModule = {
  OpenVikingWorkspace?: ComponentType;
};

const knowledgeSourceModules = import.meta.glob("./openviking/public.ts");

function missingOpenVikingWorkspace(): null {
  return null;
}

export async function loadKnowledgeSourceExtensions(): Promise<KnowledgeSourceExtension[]> {
  const modules = await Promise.all(
    Object.values(knowledgeSourceModules).map((loader) =>
      (loader as () => Promise<KnowledgeSourcePublicModule>)(),
    ),
  );
  return modules.flatMap((module) =>
    module.knowledgeSourceExtension ? [module.knowledgeSourceExtension] : [],
  );
}

export async function loadKnowledgeSourceOptions(
  signal?: AbortSignal,
): Promise<KnowledgeSourceOption[]> {
  const extensions = await loadKnowledgeSourceExtensions();
  const results = await Promise.allSettled(
    extensions.flatMap((extension) => {
      const slot = extension.slots?.dataTools;
      return slot ? [slot.listOptions(signal)] : [];
    }),
  );
  return results.flatMap((result) =>
    result.status === "fulfilled" ? result.value : [],
  );
}

export async function loadKnowledgeSourceActions(): Promise<KnowledgeSourceAction[]> {
  const extensions = await loadKnowledgeSourceExtensions();
  return extensions.flatMap((extension) => {
    const action = extension.slots?.createKnowledgeBase;
    return action ? [action] : [];
  });
}

export function knowledgeSourceOptionIdsFromRefs(
  options: KnowledgeSourceOption[],
  refs: KnowledgeSourceRef[],
): string[] {
  const serialized = new Set(refs.map(knowledgeSourceRefKey));
  return options
    .filter((option) => option.refs.some((ref) => serialized.has(knowledgeSourceRefKey(ref))))
    .map((option) => option.id);
}

export function knowledgeSourceRefsForOptionIds(
  options: KnowledgeSourceOption[],
  ids: string[],
): KnowledgeSourceRef[] {
  const selected = new Set(ids);
  const byKey = new Map<string, KnowledgeSourceRef>();
  for (const option of options) {
    if (!selected.has(option.id)) continue;
    for (const ref of option.refs) {
      byKey.set(knowledgeSourceRefKey(ref), ref);
    }
  }
  return [...byKey.values()];
}

function knowledgeSourceRefKey(ref: KnowledgeSourceRef): string {
  return [
    ref.provider,
    ref.profile_ref || "",
    ref.resource_ref || "",
    ref.version || "",
    ref.etag || "",
  ].join("\u001f");
}

export async function loadOpenVikingWorkspace(): Promise<{ default: ComponentType }> {
  const loader = knowledgeSourceModules["./openviking/public.ts"] as
    | (() => Promise<KnowledgeSourcePublicModule>)
    | undefined;
  if (!loader) {
    return { default: missingOpenVikingWorkspace };
  }
  const publicModule = await loader();
  const workspaceModule = await publicModule.loadOpenVikingWorkspace?.();
  return { default: workspaceModule?.OpenVikingWorkspace ?? missingOpenVikingWorkspace };
}
