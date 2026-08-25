import { useState } from "react";
import { ArrowRight, Database, Sparkles } from "lucide-react";

export default function HomeComposer({
  searchParams,
  setSearchParams,
}: {
  searchParams: URLSearchParams;
  setSearchParams: (params: URLSearchParams) => void;
}) {
  const [request, setRequest] = useState("");

  const openBuilder = () => {
    const params = new URLSearchParams(searchParams);
    params.set("file", "skill_builder");
    if (request.trim()) params.set("request", request.trim());
    setSearchParams(params);
  };

  return (
    <main className="flex h-full min-h-0 items-center justify-center bg-white px-5 py-10">
      <section className="w-full max-w-2xl text-center">
        <div className="mx-auto mb-5 flex h-12 w-12 items-center justify-center rounded-2xl bg-blue-50 text-blue-600">
          <Database size={24} />
        </div>
        <p className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-blue-600">
          Knowledge workspace
        </p>
        <h1 className="text-3xl font-semibold tracking-tight text-slate-900 md:text-4xl">
          从数据与知识开始，构建一个 Skill
        </h1>
        <p className="mx-auto mt-3 max-w-xl text-sm leading-6 text-slate-500">
          描述你想让 Agent 完成的任务。素材、执行结果和发布状态都由服务端确认。
        </p>
        <div className="mx-auto mt-8 max-w-2xl rounded-2xl border border-slate-200 bg-white p-2 text-left shadow-[0_12px_40px_rgba(15,23,42,0.08)]">
          <textarea
            aria-label="描述要构建的 Skill"
            value={request}
            onChange={(event) => setRequest(event.currentTarget.value)}
            placeholder="你想把哪些数据或知识加工成什么能力？"
            rows={4}
            className="w-full resize-none border-0 px-3 py-2 text-sm leading-6 text-slate-800 outline-none placeholder:text-slate-400"
          />
          <div className="flex items-center justify-between border-t border-slate-100 px-2 pt-2">
            <span className="flex items-center gap-1.5 text-xs text-slate-400">
              <Sparkles size={13} /> 服务端 Skill Builder
            </span>
            <button
              type="button"
              onClick={openBuilder}
              className="inline-flex items-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              开始构建 <ArrowRight size={15} />
            </button>
          </div>
        </div>
      </section>
    </main>
  );
}
