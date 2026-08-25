import { Database, Bell, User, Menu, PanelRight, Search } from 'lucide-react';

export default function TopNav({ searchParams, setSearchParams, onOpenMenu, onOpenAssistant }: any) {
  return (
    <header className="h-12 bg-white border-b border-slate-200 flex items-center justify-between px-2 md:px-4 shrink-0 z-20 relative min-w-0">
      <div className="flex items-center space-x-2 shrink-0 md:w-[224px] cursor-pointer" onClick={() => {
        const p = new URLSearchParams(searchParams);
        p.set('file', 'welcome');
        p.delete('explore');
        setSearchParams(p);
      }}>
        <button id="btn-mobile-menu" aria-label="打开目录" className="md:hidden p-1.5 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-md transition-colors" onClick={(e) => { e.stopPropagation(); onOpenMenu(); }}>
          <Menu size={20}/>
        </button>
        <div className="hidden md:flex w-7 h-7 bg-blue-600 rounded items-center justify-center text-white shadow-sm shrink-0">
          <Database size={16} />
        </div>
        <span className="font-semibold text-slate-800 text-[15px] tracking-tight hidden sm:block">Knowledge Asset</span>
      </div>
      
      <div className="flex items-center justify-center flex-1 h-full min-w-0 px-4">
        <div className="w-full max-w-xl relative hidden md:block">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input type="text" placeholder="全局搜索资源..." className="w-full pl-9 pr-4 py-1.5 bg-slate-100 border-transparent focus:bg-white border focus:border-blue-500 rounded-lg text-sm outline-none transition-colors" />
        </div>
      </div>

      <div className="flex items-center justify-end space-x-1 md:space-x-3 text-slate-500 shrink-0 md:w-[224px]">
        <button aria-label="通知" title="通知" className="hidden md:flex w-8 h-8 items-center justify-center rounded hover:bg-slate-100 transition-colors"><Bell size={18} /></button>
        <button aria-label="用户" title="用户" className="hidden md:flex w-8 h-8 rounded-full bg-slate-100 border border-slate-200 items-center justify-center text-slate-600 hover:bg-slate-200 transition-colors">
          <User size={16} />
        </button>
        <button id="btn-mobile-assistant" aria-label="打开分析助手" className="md:hidden p-1.5 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-md transition-colors" onClick={onOpenAssistant}>
          <PanelRight size={20}/>
        </button>
      </div>
    </header>
  );
}
