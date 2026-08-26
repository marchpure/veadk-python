import type { ConnectorDef } from '../../production/store';

export {
  WorkspaceStore as Store,
  addResource,
  agentPublicationStore,
  bootstrapWorkspace,
  connectionStore,
  customRegistryStore,
  getFullCatalog,
  getRegistry,
  getResourceDescriptor,
  getWorkspaceAdapter,
  resourceStore,
  useStore,
} from '../../production/store';

export type {
  ConnectionViewModel,
  ConnectorDef,
  WorkspaceResource,
} from '../../production/store';

// Compatibility export for older frozen-ui imports. The production catalog is
// hydrated by bootstrapWorkspace(); no connector or resource facts live here.
export const initialConnectorRegistry: ConnectorDef[] = [];
