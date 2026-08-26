import type { AuthoringEvent } from "./contracts";

const MAX_FRAME_CHARS = 256_000;

function parseFrame(frame: string): AuthoringEvent | null {
  if (!frame || frame.startsWith(":")) return null;
  let cursor = "";
  let eventType = "";
  const data: string[] = [];
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator < 0 ? line : line.slice(0, separator);
    const value = separator < 0
      ? ""
      : line.slice(separator + 1).replace(/^ /, "");
    if (field === "id") cursor = value;
    if (field === "event") eventType = value;
    if (field === "data") data.push(value);
  }
  if (data.length === 0) return null;
  const decoded: unknown = JSON.parse(data.join("\n"));
  if (!decoded || typeof decoded !== "object" || Array.isArray(decoded)) {
    throw new Error("Authoring SSE data must be an object.");
  }
  const value = decoded as Record<string, unknown>;
  const sequence = Number(value.sequence);
  const type = String(value.type ?? eventType);
  if (
    !cursor ||
    !Number.isSafeInteger(sequence) ||
    sequence < 1 ||
    !type ||
    value.terminal === undefined
  ) {
    throw new Error("Authoring SSE event is missing required fields.");
  }
  return {
    ...(value as unknown as Omit<AuthoringEvent, "cursor">),
    cursor,
    type: type as AuthoringEvent["type"],
  };
}

export async function* parseAuthoringSse(
  response: Response,
): AsyncGenerator<AuthoringEvent> {
  if (!response.body) throw new Error("Authoring stream has no response body.");
  if (!response.headers.get("content-type")?.includes("text/event-stream")) {
    throw new Error("Authoring stream returned an unexpected content type.");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value, { stream: !done }).replace(/\r\n/g, "\n");
      let boundary = buffer.indexOf("\n\n");
      while (boundary >= 0) {
        if (boundary > MAX_FRAME_CHARS) {
          throw new Error("Authoring SSE frame exceeded the client limit.");
        }
        const frame = parseFrame(buffer.slice(0, boundary));
        buffer = buffer.slice(boundary + 2);
        if (frame) yield frame;
        boundary = buffer.indexOf("\n\n");
      }
      if (buffer.length > MAX_FRAME_CHARS) {
        throw new Error("Authoring SSE frame exceeded the client limit.");
      }
      if (done) {
        if (buffer.trim()) {
          if (buffer.length > MAX_FRAME_CHARS) {
            throw new Error("Authoring SSE frame exceeded the client limit.");
          }
          const frame = parseFrame(buffer);
          if (frame) yield frame;
        }
        return;
      }
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}
