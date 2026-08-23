import React, { useEffect } from 'react';
import { X, Database, Globe, Server, FileText, ArrowRight, Library, FileSpreadsheet, Box } from 'lucide-react';
import { cn } from '../../lib/utils';

export default function CreateResourceModal({ onClose, searchParams, setSearchParams }: any) {
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [onClose]);

  const targetSpace = searchParams.get('target_space') === 'team' ? '团队工作区' : '个人工作区';

  const actions = [
    {
      id: 'connect',
      title: '连接或同步来源',
      desc: '从数据库、API 或外部系统接入数据源',
      icon: Database,
      color: 'text-blue-600',
      bg: 'bg-blue-50',
      action: () => {
        const p = new URLSearchParams(searchParams);
        p.set('file', 'add_data');
        p.set('step', '1');
        p.delete('modal');
        setSearchParams(p);
      }
    },
    {
      id: 'kb',
      title: '创建知识库',
      desc: '聚合多来源文档，发布为 Agent 可用知识',
      icon: Library,
      color: 'text-emerald-600',
      bg: 'bg-emerald-50',
      action: () => {
        const p = new URLSearchParams(searchParams);
        p.set('file', 'add_kb');
        p.delete('modal');
        setSearchParams(p);
      }
    },
    {
      id: 'skill',
      title: '创建或导入 Skill',
      desc: '从网页发现 API，或导入 MCP Server',
      icon: Server,
      color: 'text-purple-600',
      bg: 'bg-purple-50',
      action: () => {
        const p = new URLSearchParams(searchParams);
        p.set('file', 'add_data');
        p.set('step', '1');
        p.set('category', 'mcp');
        p.delete('modal');
        setSearchParams(p);
      }
    },
    {
      id: 'upload',
      title: '上传文件',
      desc: '上传本地文档或表格文件进行解析',
      icon: FileText,
      color: 'text-amber-600',
      bg: 'bg-amber-50',
      action: () => {
        const p = new URLSearchParams(searchParams);
        p.set('file', 'upload_doc');
        p.delete('modal');
        setSearchParams(p);
      }
    }
  ];

  return (
    <div 
      className="fixed inset-0 bg-slate-900/40 z-[100] flex items-center justify-center p-4 backdrop-blur-sm"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
      role="dialog" 
      aria-modal="true"
    >
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-2xl overflow-hidden animate-in zoom-in-95 duration-200">
        <div className="flex justify-between items-center p-5 border-b border-slate-100 bg-slate-50 shrink-0">
          <div>
            <h2 className="text-lg font-bold text-slate-900 flex items-center">
              <Box size={20} className="mr-2 text-blue-600" /> 新建通用资源
            </h2>
            <div className="text-xs text-slate-500 mt-1">目标位置：{targetSpace}</div>
          </div>
          <button onClick={onClose} aria-label="关闭" title="关闭" className="p-1.5 text-slate-400 hover:text-slate-600 hover:bg-slate-200 rounded-lg transition-colors outline-none">
            <X size={20} />
          </button>
        </div>
        
        <div className="p-6">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {actions.map(act => (
              <button
                key={act.id}
                onClick={act.action}
                className="flex items-start text-left p-4 border border-slate-200 rounded-xl hover:border-blue-400 hover:shadow-md transition-all group outline-none focus:ring-2 focus:ring-blue-500"
              >
                <div className={cn("w-12 h-12 rounded-xl flex items-center justify-center shrink-0 mr-4 transition-colors", act.bg, act.color)}>
                  <act.icon size={24} />
                </div>
                <div className="flex-1 min-w-0">
                  <h3 className="font-bold text-slate-800 text-base mb-1 group-hover:text-blue-700 transition-colors flex items-center">
                    {act.title}
                  </h3>
                  <p className="text-xs text-slate-500 leading-relaxed">
                    {act.desc}
                  </p>
                </div>
              </button>
            ))}
          </div>
          
          <div className="mt-6 pt-4 border-t border-slate-100 flex items-center justify-between text-xs text-slate-500">
            <span className="flex items-center">
              <Database size={14} className="mr-1.5 text-slate-400" />
              所有创建的资源均基于统一 WorkspaceResource 模型管理
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}