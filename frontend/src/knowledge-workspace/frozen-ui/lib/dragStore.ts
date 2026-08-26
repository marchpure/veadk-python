export type DragStatus = 'idle' | 'drag-start' | 'dragging' | 'valid-over' | 'invalid-over' | 'drop-pending' | 'cancelled' | 'error';

export interface DragItem {
  type: 'dataset' | 'personal_artifact' | 'team_artifact' | 'datalink' | 'element' | 'element_group' | 'folder' | 'root';
  id: string;
  name: string;
  sourceType?: string;
  fields?: number;
  hasPermission?: boolean;
  version?: string;
  artifactType?: string;
  teamOrigin?: string;
  fromTeamVersion?: string;
}

interface DragState {
  status: DragStatus;
  item: DragItem | null;
  position: { x: number, y: number };
  targetId: string | null;
  message: string;
}

let state: DragState = {
  status: 'idle',
  item: null,
  position: { x: 0, y: 0 },
  targetId: null,
  message: ''
};

const listeners = new Set<() => void>();

export const dragStore = {
  getState: () => state,
  setState: (newState: Partial<DragState>) => {
    state = { ...state, ...newState };
    listeners.forEach(l => l());
  },
  subscribe: (l: () => void) => {
    listeners.add(l);
    return () => listeners.delete(l);
  }
};
