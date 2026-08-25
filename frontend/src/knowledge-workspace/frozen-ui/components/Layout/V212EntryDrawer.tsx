import { ArrowRight, ClipboardCheck, X } from "lucide-react";

export default function V212EntryDrawer({
  searchParams,
  setSearchParams,
  onClose,
}: {
  searchParams: URLSearchParams;
  setSearchParams: (params: URLSearchParams) => void;
  onClose: () => void;
}) {
  const enterJourney = () => {
    const next = new URLSearchParams(searchParams);
    next.delete("modal");
    next.set("file", "journey_knowledge");
    next.set("step", "1");
    setSearchParams(next);
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="验收入口"
      className="fixed inset-0 z-[80] flex justify-end bg-slate-950/30"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside className="h-full w-full max-w-md bg-white p-6 shadow-2xl">
        <div className="flex items-start justify-between border-b border-slate-100 pb-4">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-50 text-blue-600">
              <ClipboardCheck size={20} />
            </div>
            <div>
              <p className="text-xs font-semibold tracking-[0.16em] text-blue-600">
                验收入口 · Review entry
              </p>
              <h2 className="mt-1 text-lg font-semibold text-slate-900">
                Skill 工作区入口
              </h2>
            </div>
          </div>
          <button
            type="button"
            aria-label="关闭验收入口"
            onClick={onClose}
            className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-800"
          >
            <X size={18} />
          </button>
        </div>
        <p className="mt-5 text-sm leading-6 text-slate-600">
          从真实数据与知识开始，经过草稿执行和评测，再进入发布边界。
          当前入口只负责验收导航，不替代服务端状态。
        </p>
        <button
          type="button"
          onClick={enterJourney}
          className="mt-6 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700"
        >
          进入企业知识旅程
          <ArrowRight size={16} />
        </button>
      </aside>
    </div>
  );
}
