import React, { useState } from 'react';
import { Database, Clock, FileText, Plus, Sparkles, LayoutDashboard, FilePieChart, ListTree, FileSpreadsheet, Calculator, Webhook, Fingerprint, Activity, UserCircle, AlertCircle, TrendingUp, Info, BadgeCheck, Lock, X } from 'lucide-react';
import { salesDatasetFields } from '../../../production/data';
import { cn } from '../../lib/utils';

export default function DatasetView({ setSearchParams, searchParams, fileId }: any) {
  const [activeTab, setActiveTab] = useState('概览');

  const dsName = fileId === 'dataset_excel' || fileId === 'dataset_mock_upload' ? 'Q3 销售数据' :
                 fileId === 'dataset_postgresql' ? 'PostgreSQL_Orders' :
                 fileId === 'dataset_view' ? '计算视图_营收明细' :
                 fileId === 'dataset_etl' ? '数据加工_宽表' :
                 '销售数据集';

  const dsSource = fileId === 'dataset_excel' || fileId === 'dataset_mock_upload' ? '本地上传 / Q3_Sales_Final.xlsx' :
                   fileId === 'dataset_postgresql' ? '生产环境 PostgreSQL / public.orders' :
                   fileId === 'dataset_view' ? '计算引擎 / revenue_view' :
                   fileId === 'dataset_etl' ? '数据加工平台 / dwd_sales' :
                   '内部数据仓库';

  const isMock = fileId !== 'dataset_sales';
  const Icon = fileId === 'dataset_excel' ? FileSpreadsheet : 
               fileId === 'dataset_view' ? Calculator : 
               fileId === 'dataset_etl' ? Webhook : Database;

  const handleExploreAction = (action?: string) => {
    const item = { id: fileId, name: dsName, type: 'dataset' };
    window.dispatchEvent(new CustomEvent('add_context_item', { detail: { item } }));
    showToast?.('已加入对话上下文，展开助手开始提问。');
    
    const p = new URLSearchParams(searchParams || window.location.search);
    p.set('pane', 'open');
    if (action) p.set('action', action);
    setSearchParams(p);
  };

  const tabs = ['概览', '数据预览', '字段', '血缘与来源', '数据质量', '使用记录'];

  return (
    <div className="max-w-6xl mx-auto p-4 md:p-8 w-full flex flex-col h-full overflow-hidden min-w-0">
      <div className="flex items-center justify-between mb-6 w-full border-b border-slate-100 pb-3 shrink-0">
        <div className="text-xs md:text-[13px] text-slate-500 flex items-center space-x-2">
          <span>个人工作区</span>
          <span className="text-slate-300">/</span>
          <span>数据连接 / 数据集</span>
          <span className="text-slate-300">/</span>
          <span className="text-slate-700 font-medium truncate max-w-[200px] md:max-w-none">{dsName}</span>
        </div>
        <button 
          onClick={() => {
            const p = new URLSearchParams(searchParams);
            p.set('file', 'welcome');
            setSearchParams(p);
          }}
          className="text-xs text-slate-500 hover:text-slate-800 flex items-center px-2 py-1 bg-white border border-slate-200 rounded hover:bg-slate-50 transition-colors shadow-sm outline-none"
        >
          <X size={14} className="mr-1" /> 返回对话
        </button>
      </div>

      <div className="flex flex-col md:flex-row md:items-start justify-between mb-8 shrink-0 space-y-4 md:space-y-0">
        <div className="min-w-0">
          <div className="flex items-center space-x-3 mb-2">
            <div className="p-2 bg-blue-100 text-blue-700 rounded-lg shrink-0">
              <Icon size={24} />
            </div>
            <h1 className="text-xl md:text-2xl font-bold text-slate-900 truncate pr-4">{dsName}</h1>
          </div>
          <div className="flex flex-wrap items-center gap-y-2 gap-x-4 text-xs text-slate-500 mt-4">
            <span className="flex items-center"><Clock size={14} className="mr-1 text-slate-400" /> 更新时间：{isMock ? '刚刚' : '2023-10-24 14:30'}</span>
            <span className="flex items-center max-w-full truncate"><FileText size={14} className="mr-1 text-slate-400 shrink-0" /> 来源：<span className="truncate max-w-[150px] md:max-w-none ml-1 text-slate-700">{dsSource}</span></span>
            <span className="flex items-center text-green-700 bg-green-50 px-2 py-1 rounded-md border border-green-100 font-medium"><BadgeCheck size={14} className="mr-1.5"/> 质量 92 分</span>
            <span className="flex items-center text-slate-600 bg-slate-50 px-2 py-1 rounded-md border border-slate-200"><Fingerprint size={14} className="mr-1.5 text-slate-400"/> 来源可追溯</span>
            <span className="flex items-center text-slate-600 bg-slate-50 px-2 py-1 rounded-md border border-slate-200"><LayoutDashboard size={14} className="mr-1.5 text-slate-400"/> 关联 12 个产物</span>
            <span className="flex items-center text-slate-600 bg-slate-50 px-2 py-1 rounded-md border border-slate-200"><Lock size={14} className="mr-1.5 text-slate-400"/> 个人私密</span>
          </div>
        </div>
        <button 
          className="flex w-full md:w-auto justify-center items-center space-x-2 bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors shadow-sm shrink-0"
          onClick={() => {
            const p = new URLSearchParams(searchParams || window.location.search);
            p.set('file', 'add_data');
            p.set('step', '1');
            setSearchParams(p);
          }}
        >
          <Plus size={16} />
          <span>添加数据</span>
        </button>
      </div>

      <div className="flex space-x-6 border-b border-slate-200 mb-6 overflow-x-auto custom-scrollbar shrink-0 min-w-0" role="tablist">
        {tabs.map(tab => (
          <button 
            key={tab} 
            role="tab"
            aria-selected={activeTab === tab}
            aria-controls={`panel-${tab}`}
            id={`tab-${tab}`}
            className={cn("pb-3 text-sm font-medium transition-colors border-b-2 whitespace-nowrap outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2", activeTab === tab ? "border-blue-600 text-blue-600" : "border-transparent text-slate-500 hover:text-slate-800")}
            onClick={() => setActiveTab(tab)}
          >
            {tab}
          </button>
        ))}
      </div>

      <div className="bg-white border border-slate-200 rounded-[12px] overflow-hidden flex-1 flex flex-col min-h-[400px] shadow-sm">
        <div className="px-4 md:px-6 py-4 border-b border-slate-200 bg-slate-50 flex flex-col md:flex-row md:items-center justify-between gap-y-4 shrink-0">
          <h2 className="font-medium text-slate-800">{activeTab}详情</h2>
          <div className="flex flex-wrap gap-2">
            <button 
              onClick={() => handleExploreAction()}
              className="flex items-center space-x-1.5 px-3 py-1.5 bg-blue-600 text-white text-xs font-medium rounded-md hover:bg-blue-700 transition-colors shadow-sm outline-none focus:ring-2 focus:ring-blue-500"
            >
              <Sparkles size={14} /> <span>用此数据探索</span>
            </button>
            <button 
              onClick={() => handleExploreAction('suggest_4')}
              className="hidden md:flex items-center space-x-1.5 px-3 py-1.5 bg-white border border-slate-200 text-slate-600 text-xs font-medium rounded-md hover:bg-slate-50 transition-colors outline-none"
            >
              <ListTree size={14} /> <span>生成模型</span>
            </button>
            <button 
              onClick={() => handleExploreAction('suggest_1')}
              className="hidden md:flex items-center space-x-1.5 px-3 py-1.5 bg-white border border-slate-200 text-slate-600 text-xs font-medium rounded-md hover:bg-slate-50 transition-colors outline-none"
            >
              <FilePieChart size={14} /> <span>生成图表</span>
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto custom-scrollbar" role="tabpanel" id={`panel-${activeTab}`} aria-labelledby={`tab-${activeTab}`}>
          {activeTab === '概览' && (
            <div className="p-4 md:p-8 flex flex-col gap-6 animate-in fade-in duration-300">
              <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                <div className="border border-slate-200 rounded-xl p-5 bg-slate-50 flex flex-col justify-center">
                  <div className="text-xs font-medium text-slate-500 mb-1 flex items-center"><ListTree size={14} className="mr-1.5" /> 总行数</div>
                  <div className="text-2xl font-bold text-slate-800">4,521</div>
                </div>
                <div className="border border-slate-200 rounded-xl p-5 bg-slate-50 flex flex-col justify-center">
                  <div className="text-xs font-medium text-slate-500 mb-1 flex items-center"><LayoutDashboard size={14} className="mr-1.5" /> 总列数 (字段数)</div>
                  <div className="text-2xl font-bold text-slate-800">8</div>
                </div>
                <div className="border border-slate-200 rounded-xl p-5 bg-slate-50 flex flex-col justify-center">
                  <div className="text-xs font-medium text-slate-500 mb-1 flex items-center"><Database size={14} className="mr-1.5" /> 存储估算</div>
                  <div className="text-2xl font-bold text-slate-800">2.4 MB</div>
                </div>
              </div>
              <div className="border border-slate-200 rounded-xl p-6 bg-white flex-1 min-h-[200px]">
                <h3 className="font-semibold text-sm text-slate-800 mb-4 flex items-center"><TrendingUp size={16} className="mr-2 text-blue-500" /> 字段空值率分布</h3>
                <div className="space-y-4">
                  <div>
                    <div className="flex justify-between text-xs mb-1"><span className="text-slate-600">Sales</span><span className="text-slate-500">0.2% 缺失</span></div>
                    <div className="w-full h-1.5 bg-slate-100 rounded-full"><div className="h-full bg-amber-400 rounded-full" style={{width: '2%'}}></div></div>
                  </div>
                  <div>
                    <div className="flex justify-between text-xs mb-1"><span className="text-slate-600">其它所有字段</span><span className="text-slate-500">100% 完整</span></div>
                    <div className="w-full h-1.5 bg-slate-100 rounded-full"><div className="h-full bg-green-500 rounded-full" style={{width: '100%'}}></div></div>
                  </div>
                </div>
              </div>
            </div>
          )}
          {activeTab === '数据预览' && (
            <div className="overflow-x-auto w-full h-full animate-in fade-in duration-300">
              <table className="w-full text-sm text-left whitespace-nowrap min-w-[700px]">
                <thead className="bg-slate-50 text-slate-600 border-b border-slate-200 text-xs sticky top-0 shadow-sm z-10">
                  <tr>
                    <th className="px-4 py-3 font-medium border-r border-slate-200 bg-slate-50">Date</th>
                    <th className="px-4 py-3 font-medium border-r border-slate-200 bg-slate-50">Region</th>
                    <th className="px-4 py-3 font-medium border-r border-slate-200 bg-slate-50">Category</th>
                    <th className="px-4 py-3 font-medium border-r border-slate-200 text-right bg-slate-50">Sales</th>
                    <th className="px-4 py-3 font-medium border-r border-slate-200 text-right bg-slate-50">Cost</th>
                    <th className="px-4 py-3 font-medium border-r border-slate-200 text-right bg-slate-50">Profit</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {Array.from({ length: 15 }).map((_, i) => (
                    <tr key={i} className="hover:bg-blue-50/30">
                      <td className="px-4 py-2 border-r border-slate-100">2026-07-0{Math.floor(Math.random()*9)+1}</td>
                      <td className="px-4 py-2 border-r border-slate-100">华东区</td>
                      <td className="px-4 py-2 border-r border-slate-100">电子产品</td>
                      <td className="px-4 py-2 border-r border-slate-100 text-right">{Math.floor(Math.random()*10000)+2000}</td>
                      <td className="px-4 py-2 border-r border-slate-100 text-right">{Math.floor(Math.random()*6000)+1000}</td>
                      <td className="px-4 py-2 border-r border-slate-100 text-right">{Math.floor(Math.random()*4000)+1000}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {activeTab === '字段' && (
            <div className="overflow-x-auto w-full animate-in fade-in duration-300">
              <table className="w-full text-sm text-left min-w-[700px]">
                <thead className="bg-slate-50 text-slate-500 border-b border-slate-200 text-xs sticky top-0 shadow-sm z-10">
                  <tr>
                    <th className="px-6 py-3 font-medium bg-slate-50">字段名称</th>
                    <th className="px-6 py-3 font-medium bg-slate-50">数据类型</th>
                    <th className="px-6 py-3 font-medium bg-slate-50">角色</th>
                    <th className="px-6 py-3 font-medium bg-slate-50">描述</th>
                    <th className="px-6 py-3 font-medium bg-slate-50">样例值</th>
                    <th className="px-6 py-3 font-medium bg-slate-50 text-center">空值率</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {salesDatasetFields.map((field, idx) => (
                    <tr key={idx} className="hover:bg-slate-50 transition-colors">
                      <td className="px-6 py-3 font-medium text-slate-700">{field.name}</td>
                      <td className="px-6 py-3 text-slate-500">
                        <span className="px-2 py-0.5 bg-slate-100 border border-slate-200 rounded text-[11px]">{field.type}</span>
                      </td>
                      <td className="px-6 py-3">
                        <span className={cn("px-2 py-0.5 rounded text-[10px] font-medium border", field.type === 'number' ? "bg-purple-50 text-purple-700 border-purple-200" : "bg-blue-50 text-blue-700 border-blue-200")}>
                          {field.type === 'number' ? '指标' : '维度'}
                        </span>
                      </td>
                      <td className="px-6 py-3 text-slate-600 text-xs">{field.desc}</td>
                      <td className="px-6 py-3 text-slate-500 text-xs font-mono">{field.type === 'number' ? '12500' : '华东区'}</td>
                      <td className="px-6 py-3 text-center text-xs text-slate-500">{field.name === 'sales_amount' ? '0.2%' : '0%'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {activeTab === '血缘与来源' && (
            <div className="p-4 md:p-8 h-full animate-in fade-in duration-300">
              <div className="flex flex-col md:flex-row items-center md:space-x-6 space-y-4 md:space-y-0">
                <div className="w-full md:w-40 h-20 bg-slate-50 border border-slate-200 rounded-lg flex flex-col items-center justify-center text-slate-500 shadow-sm shrink-0">
                  <Database size={20} className="mb-2" />
                  <span className="text-xs font-medium truncate w-full px-2 text-center">{dsSource.split(' / ')[0]}</span>
                </div>
                <div className="hidden md:block flex-1 h-px bg-slate-300 relative">
                  <div className="absolute right-0 top-1/2 -translate-y-1/2 w-2 h-2 border-t-2 border-r-2 border-slate-300 transform rotate-45"></div>
                </div>
                <div className="w-full md:w-48 h-20 bg-blue-50 border border-blue-200 rounded-lg flex flex-col items-center justify-center text-blue-700 shadow-sm relative ring-2 ring-blue-500 ring-offset-2 shrink-0">
                  <Icon size={20} className="mb-2" />
                  <span className="text-sm font-bold truncate w-full px-2 text-center">{dsName}</span>
                </div>
                <div className="hidden md:block flex-1 h-px bg-slate-300 relative">
                  <div className="absolute right-0 top-1/2 -translate-y-1/2 w-2 h-2 border-t-2 border-r-2 border-slate-300 transform rotate-45"></div>
                </div>
                <div className="w-full md:w-40 h-20 bg-slate-50 border border-slate-200 rounded-lg flex flex-col items-center justify-center text-slate-500 shadow-sm shrink-0">
                  <LayoutDashboard size={20} className="mb-2" />
                  <span className="text-xs font-medium">关联 12 个看板</span>
                </div>
              </div>
              <div className="mt-8 md:mt-12 bg-white border border-slate-200 rounded-lg p-5 text-sm">
                <h4 className="font-semibold text-slate-800 mb-4 flex items-center"><Fingerprint size={16} className="mr-2 text-slate-400" /> 详细链路信息</h4>
                <div className="space-y-3">
                  <div className="flex flex-col md:flex-row justify-between border-b border-slate-100 pb-2 md:items-center"><span className="text-slate-500 mb-1 md:mb-0">源地址</span><span className="text-slate-800 font-mono text-xs break-all">{dsSource}</span></div>
                  <div className="flex justify-between border-b border-slate-100 pb-2"><span className="text-slate-500">同步模式</span><span className="text-slate-800">全量快照提取</span></div>
                  <div className="flex justify-between"><span className="text-slate-500">最近同步记录</span><span className="text-slate-800">{isMock ? '刚刚' : '今日 02:00:00 (成功)'}</span></div>
                </div>
              </div>
            </div>
          )}
          {activeTab === '数据质量' && (
            <div className="p-4 md:p-8 h-full animate-in fade-in duration-300">
              <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4 mb-8">
                <div className="bg-white border border-slate-200 p-4 rounded-xl shadow-sm text-center">
                  <div className="text-3xl font-bold text-green-500 mb-1">92</div>
                  <div className="text-xs text-slate-500 font-medium">总体质量评分</div>
                </div>
                <div className="bg-white border border-slate-200 p-4 rounded-xl shadow-sm flex flex-col justify-center">
                  <span className="text-xs text-slate-500 mb-1">完整性 (无缺失)</span>
                  <div className="flex items-center"><div className="flex-1 h-2 bg-slate-100 rounded-full mr-3"><div className="h-full bg-amber-500 rounded-full w-[98%]"></div></div><span className="text-sm font-bold text-slate-700">98%</span></div>
                </div>
                <div className="bg-white border border-slate-200 p-4 rounded-xl shadow-sm flex flex-col justify-center">
                  <span className="text-xs text-slate-500 mb-1">唯一性 (无重复)</span>
                  <div className="flex items-center"><div className="flex-1 h-2 bg-slate-100 rounded-full mr-3"><div className="h-full bg-green-500 rounded-full w-[100%]"></div></div><span className="text-sm font-bold text-slate-700">100%</span></div>
                </div>
                <div className="bg-white border border-slate-200 p-4 rounded-xl shadow-sm flex flex-col justify-center">
                  <span className="text-xs text-slate-500 mb-1">合规性 (无异常)</span>
                  <div className="flex items-center"><div className="flex-1 h-2 bg-slate-100 rounded-full mr-3"><div className="h-full bg-amber-500 rounded-full w-[85%]"></div></div><span className="text-sm font-bold text-slate-700">85%</span></div>
                </div>
              </div>
              <h4 className="font-semibold text-slate-800 mb-4 flex items-center"><Activity size={16} className="mr-2 text-slate-400" /> 质量预警与建议</h4>
              <div className="space-y-3">
                <div className="bg-amber-50 border border-amber-200 p-4 rounded-xl flex flex-col sm:flex-row justify-between sm:items-start gap-3">
                  <div>
                    <div className="text-sm font-medium text-amber-800 mb-1 flex items-center"><AlertCircle size={14} className="mr-1.5" /> Sales 存在过大偏离异常值</div>
                    <div className="text-xs text-amber-700/80 mb-2">检测到 5 行 Sales 数值大于均值 3 倍标准差，已标记为潜在异常。</div>
                    <div className="text-xs text-amber-800 font-medium bg-amber-100/50 p-2 rounded-md border border-amber-200/50 flex items-start"><Info size={12} className="mr-1.5 mt-0.5 shrink-0"/> 建议：分析相关维度时，利用分析助手的筛选器排除此部分离群值以免影响均值计算。</div>
                  </div>
                  <span className="text-[10px] text-amber-600 bg-amber-100 px-2 py-0.5 rounded border border-amber-200 self-start shrink-0">待处理</span>
                </div>
                <div className="bg-red-50 border border-red-200 p-4 rounded-xl flex flex-col sm:flex-row justify-between sm:items-start gap-3">
                  <div>
                    <div className="text-sm font-medium text-red-800 mb-1 flex items-center"><AlertCircle size={14} className="mr-1.5" /> Sales 存在空值</div>
                    <div className="text-xs text-red-700/80 mb-2">12 行数据未填写 Sales，空值率 0.2%。</div>
                    <div className="text-xs text-red-800 font-medium bg-red-100/50 p-2 rounded-md border border-red-200/50 flex items-start"><Info size={12} className="mr-1.5 mt-0.5 shrink-0"/> 建议：系统在聚合时会自动将空值忽略，也可通过全局筛选器直接剔除该部分数据行。</div>
                  </div>
                  <span className="text-[10px] text-red-600 bg-red-100 px-2 py-0.5 rounded border border-red-200 self-start shrink-0">待处理</span>
                </div>
              </div>
            </div>
          )}
          {activeTab === '使用记录' && (
            <div className="p-4 md:p-8 h-full animate-in fade-in duration-300">
              <div className="relative border-l-2 border-slate-100 ml-3 space-y-6">
                <div className="relative pl-6">
                  <div className="absolute -left-[9px] top-1.5 w-4 h-4 rounded-full border-[3px] border-white bg-blue-500"></div>
                  <div className="text-sm text-slate-800 font-medium mb-1 flex items-center">生成 Dashboard <span className="ml-2 px-1.5 py-0.5 bg-slate-100 text-slate-500 text-[10px] rounded border border-slate-200">相关产物</span></div>
                  <div className="text-xs text-slate-500 flex items-center"><UserCircle size={12} className="mr-1"/> 您 • 刚刚</div>
                </div>
                <div className="relative pl-6">
                  <div className="absolute -left-[9px] top-1.5 w-4 h-4 rounded-full border-[3px] border-white bg-slate-300"></div>
                  <div className="text-sm text-slate-800 font-medium mb-1">完成数据初始化与入库</div>
                  <div className="text-xs text-slate-500 flex items-center"><Database size={12} className="mr-1"/> 系统 • {isMock ? '刚刚' : '2023-10-24 14:30'}</div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
