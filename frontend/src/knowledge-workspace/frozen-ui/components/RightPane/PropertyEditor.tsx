import { useEffect, type SVGProps } from 'react';

function IconBase({ children, ...props }: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      {children}
    </svg>
  );
}

function CloseIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconBase {...props}>
      <path d="M6 6l12 12" />
      <path d="M18 6 6 18" />
    </IconBase>
  );
}

function GateIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconBase {...props}>
      <path d="M12 3 5 6v5c0 4.3 2.8 7.7 7 10 4.2-2.3 7-5.7 7-10V6l-7-3Z" />
      <path d="M9 12h6" />
    </IconBase>
  );
}

function AgentEditIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconBase {...props}>
      <path d="M5 19 19 5" />
      <path d="m14 5 5 5" />
      <path d="M7 7h.01" />
      <path d="M4 12h.01" />
      <path d="M12 20h.01" />
    </IconBase>
  );
}

function CommentIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <IconBase {...props}>
      <path d="M5 6.5A3.5 3.5 0 0 1 8.5 3h7A3.5 3.5 0 0 1 19 6.5v5a3.5 3.5 0 0 1-3.5 3.5H11l-4.5 4v-4A3.5 3.5 0 0 1 3 11.5v-5Z" />
    </IconBase>
  );
}

export default function PropertyEditor({ editTarget, searchParams, setSearchParams }: any) {
  const closeEditor = () => {
    const params = new URLSearchParams(searchParams);
    params.delete('edit');
    setSearchParams(params);
  };

  useEffect(() => {
    const handleEsc = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        closeEditor();
      }
    };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  });

  const openAgentEdit = () => {
    const fileId = searchParams.get('file') ?? '';
    const item = {
      id: editTarget,
      name: `元素 ${editTarget}`,
      type: 'element',
      artifactId: fileId,
      selectionIdentity: editTarget,
    };
    window.dispatchEvent(new CustomEvent('add_context_item', { detail: { item } }));

    const params = new URLSearchParams(searchParams);
    params.delete('edit');
    params.set('pane', 'open');
    params.set('action', 'ai_edit_element');
    params.set('target_elements', editTarget);
    setSearchParams(params);
  };

  return (
    <div
      className="relative flex h-full min-h-0 flex-col overflow-hidden bg-white"
      role="dialog"
      aria-modal="true"
      aria-labelledby="property-editor-title"
    >
      <div className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-slate-50/50 p-4">
        <h3 id="property-editor-title" className="font-medium text-slate-800">属性编辑</h3>
        <button
          type="button"
          onClick={closeEditor}
          aria-label="关闭属性编辑"
          title="关闭"
          className="inline-flex h-8 w-8 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 focus:outline-none focus:ring-2 focus:ring-blue-300"
        >
          <CloseIcon className="h-4.5 w-4.5" />
        </button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto p-5">
        <section className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-amber-900">
          <div className="flex items-start gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border border-amber-200 bg-white/70">
              <GateIcon className="h-4.5 w-4.5" />
            </div>
            <div className="min-w-0">
              <h4 className="text-sm font-semibold">等待服务端属性面板</h4>
              <p className="mt-1 text-xs leading-5">
                当前元素已可作为 Agent 上下文使用，但服务端尚未返回可编辑的 typed 属性模型。页面不会通过 URL 参数、本地字段或固定数组应用修改。
              </p>
            </div>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-200 bg-slate-50 p-4">
          <dl className="grid gap-3 text-xs">
            <div>
              <dt className="font-semibold text-slate-500">选中元素</dt>
              <dd className="mt-1 break-all text-slate-800">{editTarget || '—'}</dd>
            </div>
            <div>
              <dt className="font-semibold text-slate-500">所属资源</dt>
              <dd className="mt-1 break-all text-slate-800">{searchParams.get('file') || '—'}</dd>
            </div>
            <div>
              <dt className="font-semibold text-slate-500">需要的 seam</dt>
              <dd className="mt-1 text-slate-700">ViewRevision component selection + typed editable props + skill-authoring.patch</dd>
            </div>
          </dl>
        </section>

        <div className="mt-auto grid gap-3">
          <button
            type="button"
            onClick={openAgentEdit}
            className="inline-flex min-h-9 items-center justify-center rounded-lg bg-blue-600 px-3 py-2 text-sm font-semibold text-white transition-colors hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-300"
          >
            <AgentEditIcon className="mr-2 h-4 w-4" />
            用 Agent 生成修改草稿
          </button>
          <button
            type="button"
            disabled
            aria-disabled="true"
            title="等待服务端评论接口"
            className="inline-flex min-h-9 cursor-not-allowed items-center justify-center rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-400"
          >
            <CommentIcon className="mr-2 h-4 w-4" />
            评论等待服务端接入
          </button>
          <button
            type="button"
            onClick={closeEditor}
            className="inline-flex min-h-9 items-center justify-center rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-slate-300"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
