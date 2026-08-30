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

const modulePath = "./openviking/public";

export async function loadOpenVikingApi(): Promise<OpenVikingApi | null> {
  try {
    const module = await import(/* @vite-ignore */ modulePath) as { openVikingApi?: OpenVikingApi };
    return module.openVikingApi ?? null;
  } catch {
    return null;
  }
}

export async function loadOpenVikingWorkspace(): Promise<{ default: ComponentType }> {
  const modulePath = "./openviking/OpenVikingWorkspace";
  const module = await import(/* @vite-ignore */ modulePath) as { OpenVikingWorkspace: ComponentType };
  return { default: module.OpenVikingWorkspace };
}
