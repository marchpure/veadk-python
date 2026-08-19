import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

export function ResizableSplitPanel({
  leftPanel,
  rightPanel,
  defaultLeftWidth = 48,
  minLeftWidth = 34,
  maxLeftWidth = 66,
  isRightPanelOpen = true,
}: {
  leftPanel: ReactNode;
  rightPanel: ReactNode;
  defaultLeftWidth?: number;
  minLeftWidth?: number;
  maxLeftWidth?: number;
  isRightPanelOpen?: boolean;
}) {
  const clampLeftWidth = useCallback(
    (width: number) => Math.min(Math.max(width, minLeftWidth), maxLeftWidth),
    [maxLeftWidth, minLeftWidth],
  );
  const [leftWidth, setLeftWidth] = useState(() => clampLeftWidth(defaultLeftWidth));
  const containerRef = useRef<HTMLDivElement>(null);
  const leftPanelRef = useRef<HTMLDivElement>(null);
  const draggingRef = useRef(false);
  const currentWidthRef = useRef(leftWidth);

  useEffect(() => {
    setLeftWidth((width) => clampLeftWidth(width));
  }, [clampLeftWidth]);

  const handleMouseDown = useCallback((event: React.MouseEvent) => {
    event.preventDefault();
    draggingRef.current = true;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }, []);

  const handleMouseMove = useCallback((event: MouseEvent) => {
    if (!draggingRef.current || !containerRef.current) return;
    const bounds = containerRef.current.getBoundingClientRect();
    const next = clampLeftWidth(((event.clientX - bounds.left) / bounds.width) * 100);
    currentWidthRef.current = next;
    if (leftPanelRef.current) leftPanelRef.current.style.flexBasis = `${next}%`;
  }, [clampLeftWidth]);

  const handleMouseUp = useCallback(() => {
    if (!draggingRef.current) return;
    draggingRef.current = false;
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    setLeftWidth(currentWidthRef.current);
  }, []);

  useEffect(() => {
    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);
    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [handleMouseMove, handleMouseUp]);

  return (
    <div ref={containerRef} className="resizable-split-panel flex h-full min-h-0 w-full min-w-0">
      <div
        ref={leftPanelRef}
        className="h-full min-w-0 flex-shrink-0 overflow-hidden"
        style={{
          flexBasis: isRightPanelOpen ? `${leftWidth}%` : "100%",
          flexGrow: isRightPanelOpen ? 0 : 1,
          flexShrink: isRightPanelOpen ? 0 : 1,
          maxWidth: isRightPanelOpen ? `${maxLeftWidth}%` : "100%",
          minWidth: isRightPanelOpen ? `${minLeftWidth}%` : 0,
        }}
      >
        {leftPanel}
      </div>
      <div
        role="separator"
        aria-label="Resize preview"
        onMouseDown={handleMouseDown}
        className="byaan-resize-divider group relative w-1 flex-shrink-0 cursor-col-resize bg-[#2a2a2a] transition-colors hover:bg-[#404040]"
      >
        <div className="absolute left-1/2 top-1/2 flex -translate-x-1/2 -translate-y-1/2 flex-col gap-1 opacity-0 transition-opacity group-hover:opacity-100">
          <span className="h-1 w-0.5 rounded-full bg-gray-500" />
          <span className="h-1 w-0.5 rounded-full bg-gray-500" />
          <span className="h-1 w-0.5 rounded-full bg-gray-500" />
        </div>
      </div>
      <div className="h-full min-w-0 flex-1 overflow-hidden">{rightPanel}</div>
    </div>
  );
}
