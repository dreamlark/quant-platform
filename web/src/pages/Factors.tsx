import { useEffect, useState } from 'react';
import { Card, Table, Tag, Spin, Empty, DatePicker, Space, Alert } from 'antd';
import { FactorHealth, apiGet, errMsg } from '../api/client';
import { EChart, AXIS_STYLE, baseGrid, EChartsOption } from '../components/charts';
import { COLORS } from '../theme';
import dayjs from 'dayjs';

const statusColor: Record<string, string> = { 有效: 'green', 衰减: 'gold', 失效: 'red' };

function fmt(v: number | null | undefined, digits: number) {
  return v == null || isNaN(v) ? '-' : v.toFixed(digits);
}

export default function Factors() {
  const [data, setData] = useState<FactorHealth[]>([]);
  const [loading, setLoading] = useState(true);
  const [date, setDate] = useState<string>('');
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const q = date ? `?date=${date}` : '';
    setLoading(true);
    setError(null);
    apiGet<FactorHealth[]>(`/factors/health${q}`)
      .then(setData)
      .catch((e) => setError(errMsg(e)))
      .finally(() => setLoading(false));
  }, [date]);

  if (loading) return <div className="page"><Spin /></div>;

  const columns = [
    { title: '因子', dataIndex: 'factor_name' },
    { title: 'IC', dataIndex: 'ic', render: (v: number | null | undefined) => fmt(v, 4) },
    { title: 'ICIR', dataIndex: 'icir', render: (v: number | null | undefined) => fmt(v, 2) },
    { title: '分层收益', dataIndex: 'rank_return', render: (v: number | null | undefined) => fmt(v, 4) },
    { title: '状态', dataIndex: 'status', render: (s: string) => <Tag color={statusColor[s]}>{s}</Tag> },
    { title: '权重', dataIndex: 'weight', render: (v: number | null | undefined) => fmt(v, 3) },
  ];

  const option: EChartsOption = {
    grid: baseGrid,
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: data.map((d) => d.factor_name), ...AXIS_STYLE, axisLabel: { rotate: 45, color: 'rgba(255,255,255,0.65)' } },
    yAxis: { type: 'value', ...AXIS_STYLE },
    series: [
      { name: 'IC', type: 'bar', data: data.map((d) => +fmt(d.ic, 4)), itemStyle: { color: COLORS.factor } },
      { name: '权重', type: 'line', yAxisIndex: 0, data: data.map((d) => +fmt(d.weight, 3)), itemStyle: { color: COLORS.sentiment } },
    ],
  };

  return (
    <div className="page">
      {error && (
        <Alert style={{ marginBottom: 16 }} type="error" showIcon message="因子数据加载失败" description={error} />
      )}
      <Space style={{ marginBottom: 16 }}>
        <span>日期</span>
        <DatePicker onChange={(_, s) => setDate((Array.isArray(s) ? s[0] : s) || '')} defaultValue={date ? dayjs(date) : undefined} />
      </Space>
      {data.length === 0 ? (
        <Empty description="暂无因子体检数据" />
      ) : (
        <>
          <Card title="因子健康度" className="metric-card" style={{ marginBottom: 16 }}>
            <EChart option={option} height={340} />
          </Card>
          <Card title="因子明细">
            <Table size="small" rowKey="factor_name" columns={columns} dataSource={data} pagination={false} />
          </Card>
        </>
      )}
    </div>
  );
}
