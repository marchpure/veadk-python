export const salesDatasetFields = [
  { name: 'order_id', type: 'string', desc: '订单编号' },
  { name: 'order_date', type: 'date', desc: '下单日期' },
  { name: 'region', type: 'string', desc: '大区' },
  { name: 'sales_amount', type: 'number', desc: '销售额' },
  { name: 'profit', type: 'number', desc: '利润' },
  { name: 'category', type: 'string', desc: '产品类别' },
];

export const mockKpis = [
  { label: '总销售额', value: '¥ 12,450,000', trend: '+12.5%', isUp: true },
  { label: '总利润', value: '¥ 3,210,000', trend: '+8.2%', isUp: true },
  { label: '订单数量', value: '45,678', trend: '-2.1%', isUp: false },
  { label: '客单价', value: '¥ 272', trend: '+4.0%', isUp: true },
];

export const mockTrendData = [
  { name: '周一', sales: 4000, profit: 2400 },
  { name: '周二', sales: 3000, profit: 1398 },
  { name: '周三', sales: 2000, profit: 9800 },
  { name: '周四', sales: 2780, profit: 3908 },
  { name: '周五', sales: 1890, profit: 4800 },
  { name: '周六', sales: 2390, profit: 3800 },
  { name: '周日', sales: 3490, profit: 4300 },
];