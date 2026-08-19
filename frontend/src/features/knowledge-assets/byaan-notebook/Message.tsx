import { memo } from "react";
import { Loader2 } from "lucide-react";

import { Blocks } from "../../../ui/Blocks";
import type { ByaanNotebookMessage } from "./types";

export const MessageComponent = memo(function MessageComponent({
  message,
}: {
  message: ByaanNotebookMessage;
}) {
  if (message.role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[70%] break-words rounded-xl border border-[#3a3a3a] bg-[#2a2a2a] px-3 py-1.5 text-sm leading-snug text-white">
          {message.content}
        </div>
      </div>
    );
  }

  return (
    <div className="flex">
      <div className="w-full min-w-0 text-white">
        <div className="mb-2 flex items-center gap-2 text-xs text-[#8f8f98]">
          {message.status === "running" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          <span>{message.status === "running" ? "Thinking" : message.status || "assistant"}</span>
        </div>
        {message.error ? <p className="text-sm text-red-300">{message.error}</p> : null}
        {message.blocks?.length ? (
          <Blocks blocks={message.blocks} onAction={() => {}} />
        ) : message.content ? (
          <div className="whitespace-pre-wrap text-sm leading-6 text-[#f4f4f5]">{message.content}</div>
        ) : null}
      </div>
    </div>
  );
});
