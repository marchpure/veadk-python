import React, { useState, useEffect } from 'react';
import { X, Image as ImageIcon, FileCode2, Download, Settings, Layout, Monitor } from 'lucide-react';
import { cn } from '../../lib/utils';

export default function ExportModal({ onClose, showToast }: { onClose: () => void, showToast: (m: string) => void }) {
  const [exportType, setExportType] = useState<'image' | 'html'>('image');
  const [imgRange, setImgRange] = useState<'viewport' | 'full'>('full');
  const [imgQuality, setImgQuality] = useState<'1x' | '2x' | '3x'>('2x');
  const [watermark, setWatermark] = useState(true);

  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, [onClose]);

  const handleExport = () => {
    showToast(exportType === 'html' ? 'HTML 导出成功，正在下载文件' : '图片导出成功，正在下载文件');
    onClose();
  };

  return (
    <div 
      className="fixed inset-0 bg-slate-900/40 z-50 flex items-center justify-center p-4 backdrop-blur-sm"
      onClick={(e) => { if(e.target === e.currentTarget) onClose(); }}
      role="dialog" aria-modal="true" aria-labelledby="export-modal-title"
    >
      <div className="bg-white rounded-2xl shadow-xl w-full max-w-[500px] overflow-hidden flex flex-col">
        <div className="flex justify-between items-center p-5 border-b border-slate-100 shrink-0">
          <h2 id="export-modal-title" className="text-lg font-semibold text-slate-900">导出产物</h2>
          <button onClick={onClose} aria-label="关闭" title="关闭" className="p-1 text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded transition-colors"><X size={20} /></button>
        </div>
        
        <div className="flex border-b border-slate-100">
          <button 
            className={cn("flex-1 py-3 text-sm font-medium transition-colors border-b-2", exportType === 'image' ? "border-blue-600 text-blue-600 bg-blue-50/30" : "border-transparent text-slate-600 hover:bg-slate-50")}
            onClick={() => setExportType('image')}
          >
            <ImageIcon size={16} className="inline mr-2 -mt-0.5" /> 导出为图片
          </button>
          <button 
            className={cn("flex-1 py-3 text-sm font-medium transition-colors border-b-2", exportType === 'html' ? "border-blue-600 text-blue-600 bg-blue-50/30" : "border-transparent text-slate-600 hover:bg-slate-50")}
            onClick={() => setExportType('html')}
          >
            <FileCode2 size={16} className="inline mr-2 -mt-0.5" /> 导出为 HTML
          </button>
        </div>

        <div className="p-6 overflow-y-auto max-h-[60vh] custom-scrollbar">
          {exportType === 'image' && (
            <div className="space-y-6">
              <div>
                <h3 className="text-sm font-medium text-slate-800 mb-3">截图范围</h3>
                <div className="grid grid-cols-2 gap-3">
                  <button 
                    onClick={() => setImgRange('viewport')}
                    className={cn("p-3 rounded-xl border text-left transition-all outline-none flex items-center", imgRange === 'viewport' ? "border-blue-500 bg-blue-50/50 ring-1 ring-blue-500" : "border-slate-200 hover:border-blue-300 bg-white")}
                  >
                    <Monitor size={18} className={cn("mr-3", imgRange === 'viewport' ? "text-blue-600" : "text-slate-400")} />
                    <div>
                      <div className="text-sm font-medium text-slate-900">当前视口</div>
                      <div className="text-xs text-slate-500 mt-0.5">可见区域 (1440x900)</div>
                    </div>
                  </button>
                  <button 
                    onClick={() => setImgRange('full')}
                    className={cn("p-3 rounded-xl border text-left transition-all outline-none flex items-center", imgRange === 'full' ? "border-blue-500 bg-blue-50/50 ring-1 ring-blue-500" : "border-slate-200 hover:border-blue-300 bg-white")}
                  >
                    <Layout size={18} className={cn("mr-3", imgRange === 'full' ? "text-blue-600" : "text-slate-400")} />
                    <div>
                      <div className="text-sm font-medium text-slate-900">完整看板</div>
                      <div className="text-xs text-slate-500 mt-0.5">全长滚动页 (1440x2800)</div>
                    </div>
                  </button>
                </div>
              </div>

              <div>
                <h3 className="text-sm font-medium text-slate-800 mb-3">导出质量 (倍率)</h3>
                <div className="flex bg-slate-100 p-1 rounded-lg">
                  {['1x', '2x', '3x'].map(q => (
                    <button 
                      key={q}
                      onClick={() => setImgQuality(q as any)}
                      className={cn("flex-1 py-1.5 text-sm font-medium rounded-md transition-all", imgQuality === q ? "bg-white shadow-sm text-blue-600" : "text-slate-500 hover:text-slate-700")}
                    >
                      {q} ({q==='1x'?'标清':q==='2x'?'高清':'超清'})
                    </button>
                  ))}
                </div>
              </div>

              <div className="flex items-center justify-between pt-2">
                <div className="flex items-center space-x-2">
                  <input type="checkbox" id="watermark" checked={watermark} onChange={(e) => setWatermark(e.target.checked)} className="rounded text-blue-600 focus:ring-blue-500" />
                  <label htmlFor="watermark" className="text-sm text-slate-700 font-medium">添加团队水印</label>
                </div>
                <div className="text-xs text-slate-400 flex items-center">
                  <Settings size={12} className="mr-1" /> 预估大小: ~2.4MB
                </div>
              </div>
            </div>
          )}

          {exportType === 'html' && (
            <div className="flex flex-col items-center justify-center py-6 text-center">
              <div className="w-16 h-16 bg-blue-50 rounded-2xl flex items-center justify-center mb-4 border border-blue-100">
                <FileCode2 size={28} className="text-blue-600" />
              </div>
              <h3 className="text-base font-semibold text-slate-900 mb-2">All-in-HTML 离线包</h3>
              <p className="text-sm text-slate-500 max-w-sm leading-relaxed">
                将数据、交互和视图打包成单个轻量级 HTML 文件。<br/>无需后端服务，支持完整的筛选和下钻操作，方便邮件发送与离线汇报。
              </p>
            </div>
          )}
        </div>

        <div className="p-5 border-t border-slate-100 bg-slate-50 flex justify-end shrink-0">
          <button onClick={handleExport} className="w-full py-2.5 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-sm font-medium transition-colors shadow-sm flex items-center justify-center">
            <Download size={18} className="mr-2" />
            {exportType === 'image' ? '生成并下载图片' : '下载 HTML 包'}
          </button>
        </div>

      </div>
    </div>
  );
}