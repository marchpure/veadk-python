import { Markdown } from "../../../ui/Markdown";

export function AssistantMessage({
  content,
  streaming = false,
}: {
  content: string;
  streaming?: boolean;
}) {
  if (!content) return null;
  return (
    <div className="kw-assistant-message">
      <Markdown
        text={content}
        allowRawHtml={false}
        streaming={streaming}
        className="kw-assistant-markdown"
      />
    </div>
  );
}
