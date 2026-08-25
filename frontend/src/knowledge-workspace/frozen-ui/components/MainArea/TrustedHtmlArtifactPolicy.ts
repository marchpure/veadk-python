const ALLOWED_EVENTS = new Set([
  'filter.change',
  'drill.request',
  'selection.change',
  'export.request',
  'context.reference',
  'refresh.request',
]);
const FORBIDDEN_ELEMENTS = new Set([
  'SCRIPT',
  'IFRAME',
  'FRAME',
  'OBJECT',
  'EMBED',
  'FORM',
  'INPUT',
  'TEXTAREA',
  'VIDEO',
  'AUDIO',
  'SOURCE',
  'LINK',
]);
const URL_ATTRIBUTES = new Set(['href', 'src', 'srcset', 'action', 'formaction']);
export const MAX_TRUSTED_HTML_BYTES = 5 * 1024 * 1024;

export type TrustedArtifactEvent = {
  type:
    | 'filter.change'
    | 'drill.request'
    | 'selection.change'
    | 'export.request'
    | 'context.reference'
    | 'refresh.request';
  revisionId: string;
  elementId?: string;
  field?: string;
  value?: string;
  format?: string;
};

export function isSameOriginHttpUrl(uri: string, origin: string): boolean {
  try {
    const url = new URL(uri, origin);
    return url.origin === origin && /^https?:$/.test(url.protocol);
  } catch {
    return false;
  }
}

export function parseTrustedContentLength(value: string | null): number {
  if (!value || !/^(0|[1-9]\d*)$/.test(value)) {
    throw new Error('HTML revision 缺少有效的 Content-Length。');
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed <= 0 || parsed > MAX_TRUSTED_HTML_BYTES) {
    throw new Error('HTML revision 的 Content-Length 超出安全范围。');
  }
  return parsed;
}

export function isHtmlMediaType(value: string | null): boolean {
  return value?.split(';', 1)[0]?.trim().toLowerCase() === 'text/html';
}

function assertSafeCss(value: string): void {
  const normalized = value.toLowerCase();
  if (
    /\\|@import|\burl\s*\(|\b(?:-webkit-)?image-set\s*\(|\bsrc\s*\(|(?:https?|data|blob|file):|\/\//.test(
      normalized,
    )
  ) {
    throw new Error('HTML revision 样式包含网络资源或转义 URL。');
  }
}

export async function sha256Text(value: string): Promise<string> {
  return sha256Bytes(new TextEncoder().encode(value));
}

export async function sha256Bytes(value: BufferSource): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', value);
  return Array.from(new Uint8Array(digest))
    .map((item) => item.toString(16).padStart(2, '0'))
    .join('');
}

export function validateTrustedArtifactHtml(source: string): Document {
  const documentValue = new DOMParser().parseFromString(source, 'text/html');
  if (documentValue.querySelector('parsererror')) {
    throw new Error('HTML revision 无法解析。');
  }
  for (const element of documentValue.querySelectorAll('*')) {
    if (FORBIDDEN_ELEMENTS.has(element.tagName)) {
      throw new Error(`HTML revision 包含不允许的 ${element.tagName.toLowerCase()} 元素。`);
    }
    for (const attribute of Array.from(element.attributes)) {
      const name = attribute.name.toLowerCase();
      const value = attribute.value.trim().toLowerCase();
      if (
        name.startsWith('on') ||
        URL_ATTRIBUTES.has(name) ||
        name.endsWith(':href')
      ) {
        throw new Error(`HTML revision 包含不允许的 ${name} 属性。`);
      }
      if (name === 'style') assertSafeCss(value);
    }
    const eventType = element.getAttribute('data-artifact-event');
    if (eventType && !ALLOWED_EVENTS.has(eventType)) {
      throw new Error(`HTML revision 包含未知交互事件：${eventType}`);
    }
  }
  for (const style of documentValue.querySelectorAll('style')) {
    assertSafeCss(style.textContent ?? '');
  }
  return documentValue;
}

export function eventFromElement(
  element: HTMLElement,
  revisionId: string,
): TrustedArtifactEvent | null {
  const type = element.dataset.artifactEvent;
  if (!type || !ALLOWED_EVENTS.has(type)) return null;
  const selectValue =
    element.tagName === 'SELECT'
      ? (element as HTMLSelectElement).value
      : element.dataset.value;
  return {
    type: type as TrustedArtifactEvent['type'],
    revisionId,
    ...(element.dataset.elementId ? { elementId: element.dataset.elementId } : {}),
    ...(element.dataset.field ? { field: element.dataset.field } : {}),
    ...(selectValue !== undefined ? { value: selectValue } : {}),
    ...(element.dataset.format ? { format: element.dataset.format } : {}),
  };
}
