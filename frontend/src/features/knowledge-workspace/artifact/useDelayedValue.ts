import { useEffect, useState } from "react";

export function useDelayedValue<T>(value: T, delayMs: number): T {
  const [delayedValue, setDelayedValue] = useState(value);

  useEffect(() => {
    if (delayMs <= 0) {
      setDelayedValue(value);
      return undefined;
    }
    const timer = window.setTimeout(() => setDelayedValue(value), delayMs);
    return () => window.clearTimeout(timer);
  }, [delayMs, value]);

  return delayedValue;
}
