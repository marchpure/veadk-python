import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

function safeHref(href?: string): string | undefined {
  if (!href) return undefined;
  try {
    const parsed = new URL(href, window.location.origin);
    return ["http:", "https:", "mailto:"].includes(parsed.protocol)
      ? href
      : undefined;
  } catch {
    return undefined;
  }
}

function stableMarkdown(value: string, streaming: boolean): string {
  if (!streaming) return value;
  const fenceCount = (value.match(/```/g) ?? []).length;
  return fenceCount % 2 === 1 ? `${value}\n\`\`\`` : value;
}

export function MarkdownAnswer({
  content,
  streaming = false,
}: {
  content: string;
  streaming?: boolean;
}) {
  return (
    <div className="agent-markdown" data-streaming={streaming || undefined}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        skipHtml
        urlTransform={(url) => safeHref(url) ?? ""}
        components={{
          a: ({ href, children }) => {
            const safe = safeHref(href);
            return safe ? (
              <a href={safe} target="_blank" rel="noreferrer noopener">
                {children}
              </a>
            ) : <span>{children}</span>;
          },
          pre: ({ children }) => (
            <div className="agent-code">
              <div className="agent-code__label">Code</div>
              <pre>{children}</pre>
            </div>
          ),
          table: ({ children }) => (
            <div className="agent-table-wrap">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {stableMarkdown(content, streaming)}
      </ReactMarkdown>
    </div>
  );
}
