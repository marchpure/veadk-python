if (typeof window !== 'undefined' && !window.PointerEvent) {
  window.PointerEvent = MouseEvent as typeof PointerEvent
}
