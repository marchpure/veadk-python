import React from 'react';
import ArtifactHeader from './ArtifactHeader';
import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts';

export default function ChartView({ fileId, isTeam = false, searchParams, setSearchParams, showToast }: any) {
  const editTarget = searchParams.get('edit');
  const handleElementClick = (target: string) => {
    if (isTeam) return;
    const p = new URLSearchParams(searchParams);
    p.set('edit', target);
    setSearchParams(p);
  };

  const data = [
    { name: '华东区', value: 400 },
    { name: '华南区', value: 300 },
    { name: '华北区', value: 300 },
    { name: '西部区', value: 200 },
  ];
  const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#8b5cf6'];

  const currentResource = fileId ? (JSON.parse(localStorage.getItem('v2103_resources') || '[]').find((r:any) => r.id === fileId || r.resourceId === fileId)) : null;
  const dynamicTitle = searchParams.get('custom_name') || currentResource?.displayName || '分析产物图表';
  const typeLabel = currentResource?.resourceKind === 'skill' ? 'Skill Component' : 'Chart';

  return (
    <div className="p-6 max-w-6xl mx-auto pb-24 w-full">
      <ArtifactHeader 
        title={dynamicTitle} 
        typeLabel={typeLabel}
        isTeam={isTeam} 
        version="V2.1" 
        editTarget={editTarget} 
        onElementClick={handleElementClick} 
        searchParams={searchParams}
        setSearchParams={setSearchParams}
        showToast={showToast}
      />
      
      {currentResource?.resourceKind === 'skill' ? (
        <div className="bg-white border border-slate-200 rounded-[12px] p-8 mt-6">
          <div className="flex items-center justify-between border-b border-slate-100 pb-4 mb-4">
             <h3 className="font-bold text-slate-800 text-lg">Skill Component Overview</h3>
             <span className="bg-purple-100 text-purple-800 text-xs px-2 py-1 rounded font-mono">Adapter: {currentResource.subtype}</span>
          </div>
          <div className="grid grid-cols-2 gap-6">
             <div className="bg-slate-50 rounded-xl p-4 border border-slate-100">
               <div className="text-xs font-bold text-slate-500 mb-2 uppercase tracking-wider">Manifest Schema</div>
               <div className="font-mono text-xs text-slate-700 bg-white p-3 rounded border border-slate-200 h-[200px] overflow-auto">
                 {`{
  "name": "${currentResource.name}",
  "version": "${currentResource.version}",
  "capabilities": ["executable"],
  "endpoints": ["/api/v1/execute"]
}`}
               </div>
             </div>
             <div className="bg-slate-50 rounded-xl p-4 border border-slate-100 flex flex-col justify-center items-center text-center">
               <div className="text-slate-400 mb-2">测试控制台已就绪</div>
               <button className="bg-blue-600 text-white px-4 py-2 rounded-lg font-bold shadow-sm hover:bg-blue-700">执行测试请求</button>
             </div>
          </div>
        </div>
      ) : (
        <div 
          className={`bg-white border rounded-[12px] p-6 relative cursor-pointer transition-colors mt-6 outline-none focus-within:ring-2 focus-within:ring-blue-500 ${editTarget === 'chart_pie' ? 'ring-2 ring-blue-500 border-transparent' : 'border-slate-200 hover:border-blue-300'}`}
          onClick={() => handleElementClick('chart_pie')}
          role="button"
          tabIndex={0}
        >
          <h3 className="font-medium text-slate-800 mb-6 text-center">业务维度分布</h3>
          <div className="h-[400px] w-full">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={data}
                  cx="50%"
                  cy="50%"
                  innerRadius={100}
                  outerRadius={140}
                  fill="#8884d8"
                  paddingAngle={2}
                  dataKey="value"
                  label
                >
                  {data.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip contentStyle={{ borderRadius: '8px', border: 'none', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }} />
                <Legend verticalAlign="bottom" height={36} />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  );
}