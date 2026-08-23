import React from 'react';
import { Sparkles, BarChart2, TrendingUp, AlertCircle, FileText, LayoutDashboard, Database, ArrowRight } from 'lucide-react';
import { cn } from '../../lib/utils';

export default function ExploreView({ fileId, setSearchParams, searchParams }: any) {
  // Any file selected implies context, unless it's explicitly the welcome or generic overviews.
  const hasContext = fileId !== 'welcome' && fileId !== 'data_overview' && fileId !== 'team_empty';
  
  if (!hasContext) {
    return (
      <div className="h-full w-full flex flex-col items-center justify-center p-8 text-center bg-white">
        <div className="w-20 h-20 bg-blue-50 rounded-2xl flex items-center justify-center mb-6 border border-blue-100 shadow-sm">
          <Database size={36} className="text-blue-600" />
        </div>
        <h2 className="text-2xl font-bold text-slate-900 mb-3">请选择探索的数据上下文</h2>
        <p className="text-slate-500 text-sm mb-8 max-w-md leading-relaxed">
          AI 分析助手需要基于具体的数据集或产物进行探索。<br/>请先在左侧目录或下方选择一个数据源或产物。
        </p>
        <button 
          className="bg-blue-600 hover:bg-blue-700 text-white px-6 py-2.5 rounded-lg text-sm font-medium transition-colors shadow-sm flex items-center"
          onClick={() => {
            const p = new URLSearchParams(searchParams || window.location.search);
            p.delete('explore');
            p.set('file', 'data_overview');
            p.set('explore_pending', 'true');
            setSearchParams(p);
          }}
        >
          前往数据源选择 <ArrowRight size={16} className="ml-2" />
        </button>
      </div>
    );
  }

  const contextName = fileId === 'dataset_mock_upload' || fileId === 'dataset_excel' ? 'Q3 销售数据' :
                      fileId === 'dataset_postgresql' ? 'PostgreSQL_Orders' :
                      fileId === 'dataset_view' ? '计算视图_营收明细' :
                      fileId === 'dataset_etl' ? '数据加工_宽表' :
                      '销售数据集';

  const suggestions = [
    { icon: LayoutDashboard, title: '生成经营分析看板', desc: '按周展示销售趋势及利润占比' },
    { icon: TrendingUp, title: '查看销售趋势', desc: '近三个月的各区销售额环比变化' },
    { icon: BarChart2, title: '分析地区差异', desc: '对比各地区客单价及订单分布' },
    { icon: AlertCircle, title: '查找异常数据', desc: '识别近期销量陡降的商品类别' },
    { icon: FileText, title: '创建指标定义', desc: '生成“毛利率”的语义模型定义' }
  ];

  return (
    <div className="max-w-4xl mx-auto p-12 w-full">
      <div className="mb-12">
        <div className="flex items-center space-x-2 text-blue-600 font-medium mb-4 text-sm bg-blue-50 w-fit px-3 py-1 rounded-full border border-blue-100">
          <Sparkles size={16} />
          <span>智能分析探索</span>
        </div>
        <h1 className="text-3xl font-bold text-slate-900 mb-4 tracking-tight">你想了解关于 <span className="text-blue-600 border-b-2 border-blue-200 pb-0.5">{contextName}</span> 的什么？</h1>
        <p className="text-slate-500 text-base max-w-2xl leading-relaxed">请在右侧对话框输入您的分析需求，或直接从下方选择一个预设的探索任务模板。</p>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {suggestions.map((item, idx) => {
          const Icon = item.icon;
          return (
            <button 
              key={idx}
              className="w-full text-left group bg-white border border-slate-200 hover:border-blue-300 rounded-[12px] p-5 cursor-pointer transition-all duration-200 outline-none focus:ring-2 focus:ring-blue-500"
              onClick={() => {
                const p = new URLSearchParams(searchParams || window.location.search);
                p.set('action', 'suggest_' + idx);
                setSearchParams(p);
              }}
            >
              <div className="flex items-start space-x-4">
                <div className="w-10 h-10 rounded-lg bg-blue-50 border border-blue-100 text-blue-600 flex items-center justify-center shrink-0 group-hover:bg-blue-600 group-hover:text-white transition-colors">
                  <Icon size={20} />
                </div>
                <div>
                  <h3 className="font-semibold text-slate-900 group-hover:text-blue-700 transition-colors mb-1.5">{item.title}</h3>
                  <p className="text-xs text-slate-500 leading-relaxed">{item.desc}</p>
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}