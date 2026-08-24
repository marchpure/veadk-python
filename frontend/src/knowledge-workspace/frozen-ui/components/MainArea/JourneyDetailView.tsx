import React from 'react';
import { AlertTriangle, ArrowLeft, CheckCircle2, Database, FileText, ShieldCheck, Webhook } from 'lucide-react';

const JOURNEYS: Record<string, { title: string; description: string; icon: typeof FileText }> = {
  journey_knowledge: { title: '企业知识', description: '将可信知识素材调试为可评测的 Skill 草稿。', icon: FileText },
  journey_oracle_excel: { title: 'Oracle + Excel', description: '外部凭证就绪后，可接入数据库与表格素材。', icon: Database },
  journey_web_api: { title: '网页 / API', description: 'Web/API 连接器的生产读取由凭证与策略控制。', icon: Webhook },
  journey_financial_monitor: { title: '金融监控', description: '使用历史数据评测监控类 Skill 的质量与新鲜度。', icon: ShieldCheck },
  journey_workday_mcp: { title: 'Workday MCP', description: 'MCP 连接保持 allowlist 与凭证边界。', icon: Database },
};

const stageFor = (step: string) => {
  if (['1', '2', '3'].includes(step)) return 0;
  if (['4', '5', '6'].includes(step)) return 1;
  return 2;
};

export default function JourneyDetailView({ fileId, searchParams, setSearchParams }: any) {
  const journey = JOURNEYS[fileId] ?? JOURNEYS.journey_knowledge;
  const step = searchParams.get('step') ?? '1';
  const errorState = searchParams.get('error_state');
  const stage = stageFor(step);
  const Icon = journey.icon;
  const setStep = (next: string) => {
    const params = new URLSearchParams(searchParams);
    params.set('step', next);
    params.delete('error_state');
    setSearchParams(params);
  };
  const returnHome = () => {
    const params = new URLSearchParams(searchParams);
    params.set('file', 'welcome');
    ['step', 'error_state', 'pane'].forEach((key) => params.delete(key));
    setSearchParams(params);
  };
  const stageLabels = ['准备素材', '调试能力', '发布给 Agent'];
  const gated = stage === 2 || errorState;

  return (
    <div className="p-4 md:p-8 max-w-5xl mx-auto w-full">
      <button className="text-sm text-slate-500 hover:text-slate-900 flex items-center mb-5" onClick={returnHome}>
        <ArrowLeft size={15} className="mr-1.5" /> 返回工作区
      </button>
      <div className="bg-white border border-slate-200 rounded-2xl shadow-sm overflow-hidden">
        <div className="p-6 border-b border-slate-100 flex items-start gap-4">
          <div className="w-11 h-11 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center"><Icon size={22} /></div>
          <div>
            <h1 className="text-xl font-semibold text-slate-900">{journey.title} Skill</h1>
            <p className="text-sm text-slate-500 mt-1">{journey.description}</p>
          </div>
        </div>
        <div className="px-6 py-5 border-b border-slate-100 grid grid-cols-3 gap-3">
          {stageLabels.map((label, index) => (
            <button key={label} className={`text-left rounded-lg p-3 border ${index === stage ? 'border-blue-300 bg-blue-50' : index < stage ? 'border-green-200 bg-green-50' : 'border-slate-200 bg-slate-50'}`} onClick={() => setStep(index === 0 ? '1' : index === 1 ? '4' : '7')}>
              <div className="text-[11px] text-slate-400">阶段 {index + 1}</div>
              <div className="text-sm font-medium text-slate-800 mt-1 flex items-center gap-1.5">{index < stage && <CheckCircle2 size={14} className="text-green-600" />}{label}</div>
            </button>
          ))}
        </div>
        <div className="p-6 min-h-[280px]">
          {errorState ? (
            <div className="rounded-xl border border-amber-200 bg-amber-50 p-5 text-amber-900 flex gap-3">
              <AlertTriangle size={20} className="shrink-0" />
              <div><div className="font-medium">当前连接或渲染被阻断</div><div className="text-sm mt-1">服务端返回了可恢复的错误状态；请修复凭证、数据结构或策略后重试。</div></div>
            </div>
          ) : gated ? (
            <div className="rounded-xl border border-slate-200 bg-slate-50 p-5">
              <div className="font-medium text-slate-800">发布与正式调用需要下一阶段能力</div>
              <div className="text-sm text-slate-500 mt-2">STEP 3 仅提供真实草稿执行、结果、视图、评测与策略门；PublishedSkillVersion、Registry、Scheduler 和跨 Agent 调用属于 STEP 4。</div>
            </div>
          ) : (
            <div>
              <h2 className="text-lg font-semibold text-slate-900">{stage === 0 ? '选择并验证素材' : '调试与评测 Skill 草稿'}</h2>
              <p className="text-sm text-slate-500 mt-2">主工作区中的真实 BFF 命令负责 source/profile/clean、skill-draft.run、evaluation.run 和 assistant.turn；此处只承载状态入口。</p>
              <div className="flex gap-2 mt-6">
                <button className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700" onClick={() => setStep(stage === 0 ? '4' : '6')}>{stage === 0 ? '开始构建 Skill' : '运行评测'}</button>
                <button className="px-4 py-2 rounded-lg border border-slate-200 text-sm text-slate-700 hover:bg-slate-50" onClick={() => setStep(stage === 0 ? '2' : '5')}>查看构建详情</button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
