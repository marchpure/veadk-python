/** Vendor-neutral contract exposed to the Knowledge Studio host. */
export interface KnowledgeSourceRef {
  provider: string;
  profile_ref?: string;
  resource_ref?: string;
  version?: string;
  etag?: string;
}

export interface KnowledgeSourceCapability {
  id: string;
  enabled: boolean;
}

export interface KnowledgeSourceExtension {
  provider: string;
  displayName: string;
  capabilities: readonly KnowledgeSourceCapability[];
}
