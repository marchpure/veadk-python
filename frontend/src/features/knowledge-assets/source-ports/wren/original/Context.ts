import { createContext } from "react";

import type { ClickPayload } from "./types";

export const DiagramContext = createContext<{
  onMoreClick: (payload: ClickPayload) => void;
  onNodeClick: (payload: ClickPayload) => void;
  onAddClick: (payload: ClickPayload) => void;
} | null>(null);
