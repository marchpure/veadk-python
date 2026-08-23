import React from 'react';
import { FolderX, ShieldAlert, AlertCircle } from 'lucide-react';

export default function EmptyState({ type }: { type: 'empty_dir' | 'no_permission' | 'no_data' }) {
  const config = {
    empty_dir: { icon: FolderX, title: '目录为空', desc: '当前文件夹下没有文件' },
    no_permission: { icon: ShieldAlert, title: '暂无权限', desc: '您没有访问该数据的权限，请联系管理员申请。' },
    no_data: { icon: AlertCircle, title: '暂无数据', desc: '未找到相关数据' },
  };
  const { icon: Icon, title, desc } = config[type];
  
  return (
    <div className="h-full w-full flex flex-col items-center justify-center text-slate-500">
      <Icon size={48} className="mb-4 text-slate-300" />
      <h3 className="text-lg font-medium text-slate-700 mb-2">{title}</h3>
      <p className="text-sm">{desc}</p>
    </div>
  );
}