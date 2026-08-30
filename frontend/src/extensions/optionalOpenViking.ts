import type { ComponentType } from "react";

export interface OpenVikingProfile {
  profile_id: string;
  status: string;
  display_name?: string;
  root_resource_ref: string;
}

export interface OpenVikingApi {
  listProfiles(signal?: AbortSignal): Promise<OpenVikingProfile[]>;
}

type OpenVikingPublicModule = {
  openVikingApi?: OpenVikingApi;
};

type OpenVikingWorkspaceModule = {
  OpenVikingWorkspace?: ComponentType;
};

const openVikingPublicModules = import.meta.glob("./openviking/public.ts");
const openVikingWorkspaceModules = import.meta.glob("./openviking/OpenVikingWorkspace.tsx");

function missingOpenVikingWorkspace(): null {
  return null;
}

export async function loadOpenVikingApi(): Promise<OpenVikingApi | null> {
  const loader = openVikingPublicModules["./openviking/public.ts"] as
    | (() => Promise<OpenVikingPublicModule>)
    | undefined;
  if (!loader) return null;
  const module = await loader();
  return module.openVikingApi ?? null;
}

export async function loadOpenVikingWorkspace(): Promise<{ default: ComponentType }> {
  const loader = openVikingWorkspaceModules["./openviking/OpenVikingWorkspace.tsx"] as
    | (() => Promise<OpenVikingWorkspaceModule>)
    | undefined;
  if (!loader) {
    return { default: missingOpenVikingWorkspace };
  }
  const module = await loader();
  return { default: module.OpenVikingWorkspace ?? missingOpenVikingWorkspace };
}
