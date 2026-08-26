import { useEffect, useRef, useState } from 'react';
import './TrustedHtmlArtifactRenderer.css';
import {
  eventFromElement,
  isHtmlMediaType,
  isSameOriginHttpUrl,
  MAX_TRUSTED_HTML_BYTES,
  parseTrustedContentLength,
  sha256Bytes,
  validateTrustedArtifactHtml,
  type TrustedArtifactEvent,
} from './TrustedHtmlArtifactPolicy';
export type { TrustedArtifactEvent } from './TrustedHtmlArtifactPolicy';

type StorageRef = {
  uri: string;
  sha256: string;
  mediaType?: string;
  media_type?: string;
  bytes?: number | null;
};

type TrustedViewRevision = {
  id: string;
  manifest: {
    cspProfile?: string;
    csp_profile?: string;
  };
  resultRef?: StorageRef | null;
  result_ref?: StorageRef | null;
};

export function TrustedHtmlArtifactRenderer({
  revision,
  onEvent,
}: {
  revision: TrustedViewRevision | null;
  onEvent?: (event: TrustedArtifactEvent) => void;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const onEventRef = useRef(onEvent);
  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);
  const [state, setState] = useState<'empty' | 'loading' | 'ready' | 'error'>(
    revision ? 'loading' : 'empty',
  );
  const [message, setMessage] = useState('');

  const resultRef = revision?.resultRef ?? revision?.result_ref;
  const mediaType = resultRef?.mediaType ?? resultRef?.media_type;
  const profile =
    revision?.manifest?.cspProfile ?? revision?.manifest?.csp_profile;
  // Fetch identity is the immutable artifact identity, not the parent
  // render's object/callback identities. Re-rendering the shell must not
  // clean up and abort a valid artifact request.
  const revisionKey = revision
    ? [
        revision.id,
        profile ?? '',
        resultRef?.uri ?? '',
        resultRef?.sha256 ?? '',
        resultRef?.bytes ?? '',
        mediaType ?? '',
      ].join('|')
    : '';

  useEffect(() => {
    if (!revision) {
      setState('empty');
      setMessage('');
      return;
    }
    const host = hostRef.current;
    if (!host) return;
    const root = host.shadowRoot ?? host.attachShadow({ mode: 'open' });
    if (
      profile !== 'trusted-renderer-v1' ||
      !resultRef ||
      mediaType !== 'text/html' ||
      !/^[0-9a-f]{64}$/.test(resultRef.sha256) ||
      typeof resultRef.bytes !== 'number' ||
      !Number.isSafeInteger(resultRef.bytes) ||
      resultRef.bytes <= 0 ||
      resultRef.bytes > MAX_TRUSTED_HTML_BYTES ||
      !isSameOriginHttpUrl(resultRef.uri, window.location.origin)
    ) {
      root.replaceChildren();
      setState('error');
      setMessage('当前 ViewRevision 没有可由平台安全读取的 HTML 地址。');
      return;
    }

    let active = true;
    setState('loading');
    setMessage('');
    void fetch(resultRef.uri, {
      credentials: 'same-origin',
      headers: { Accept: 'text/html' },
    })
      .then(async (response) => {
        if (
          !response.ok ||
          !isSameOriginHttpUrl(response.url, window.location.origin) ||
          !isHtmlMediaType(response.headers.get('content-type'))
        ) {
          throw new Error(`HTML revision 加载失败（HTTP ${response.status}）。`);
        }
        const responseLength = parseTrustedContentLength(
          response.headers.get('content-length'),
        );
        if (responseLength !== resultRef.bytes) {
          throw new Error('HTML revision 响应长度与 manifest 不一致。');
        }
        const bytes = await response.arrayBuffer();
        if (bytes.byteLength !== responseLength) {
          throw new Error('HTML revision 长度校验失败。');
        }
        if (await sha256Bytes(bytes) !== resultRef.sha256) {
          throw new Error('HTML revision 摘要校验失败。');
        }
        const source = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
        const parsed = validateTrustedArtifactHtml(source);
        const fragment = document.createDocumentFragment();
        for (const style of Array.from(parsed.head.querySelectorAll('style'))) {
          fragment.append(style.cloneNode(true));
        }
        for (const child of Array.from(parsed.body.childNodes)) {
          fragment.append(child.cloneNode(true));
        }
        if (!active) return;
        root.replaceChildren(fragment);
        setState('ready');
      })
      .catch((error: unknown) => {
        if (!active) return;
        root.replaceChildren();
        setState('error');
        setMessage(error instanceof Error ? error.message : 'HTML revision 加载失败。');
      });

    return () => {
      // Do not abort a same-origin immutable artifact request during React
      // StrictMode's development remount. Aborting here is reported by the
      // real browser as a failed business request even though the subsequent
      // mount completes successfully. The active guard prevents stale data
      // from committing after a revision switch.
      active = false;
      root.replaceChildren();
    };
  }, [revisionKey]);

  useEffect(() => {
    if (!revision) return;
    const host = hostRef.current;
    if (!host) return;
    const root = host.shadowRoot ?? host.attachShadow({ mode: 'open' });
    const dispatch = (target: EventTarget | null) => {
      const element =
        target instanceof Element
          ? target.closest<HTMLElement>('[data-artifact-event]')
          : null;
      if (!element) return;
      const detail = eventFromElement(element, revision.id);
      if (!detail) return;
      onEventRef.current?.(detail);
      host.dispatchEvent(
        new CustomEvent<TrustedArtifactEvent>('trusted-artifact-event', {
          bubbles: true,
          detail,
        }),
      );
    };
    const click = (event: Event) => {
      const element =
        event.target instanceof Element
          ? event.target.closest<HTMLElement>('[data-artifact-event]')
          : null;
      if (element?.dataset.artifactEvent !== 'filter.change') dispatch(event.target);
    };
    const change = (event: Event) => {
      const element =
        event.target instanceof Element
          ? event.target.closest<HTMLElement>('[data-artifact-event]')
          : null;
      if (element?.dataset.artifactEvent === 'filter.change') dispatch(event.target);
    };
    root.addEventListener('click', click);
    root.addEventListener('change', change);
    return () => {
      root.removeEventListener('click', click);
      root.removeEventListener('change', change);
    };
  }, [revision?.id]);

  if (!revision) {
    return (
      <section className="trusted-artifact-state" aria-label="Dashboard 空态">
        <h2>暂无 HTML revision</h2>
        <p>请先选择真实 Golden context，由 Agent 生成 SkillDraft 和 BuildPlan，并确认 Runner 执行。</p>
      </section>
    );
  }
  return (
    <section className="trusted-artifact-shell" aria-busy={state === 'loading'}>
      {state === 'loading' && (
        <div className="trusted-artifact-loading" aria-live="polite">
          正在验证 HTML revision…
        </div>
      )}
      {state === 'error' && (
        <div className="trusted-artifact-loading is-error" role="alert">
          <strong>无法展示 HTML revision</strong>
          <span>{message}</span>
        </div>
      )}
      <div ref={hostRef} className="trusted-artifact-host" />
    </section>
  );
}
