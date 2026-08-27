const values = new Map<string, unknown>();

export function readQuery<T>(key: string): T | undefined {
  return values.get(key) as T | undefined;
}

export function writeQuery<T>(key: string, value: T): T {
  values.set(key, value);
  return value;
}

export function invalidateQuery(keyPrefix: string): void {
  for (const key of values.keys()) {
    if (key === keyPrefix || key.startsWith(`${keyPrefix}:`)) values.delete(key);
  }
}
