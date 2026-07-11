import React, { useEffect, useState } from 'react';
import { Card, Table, Tag, Spin, Empty, DatePicker, Space } from 'antd';
import { api, FactorHealth } from '../api/client';
import { EChart, AXIS_STYLE, baseGrid } from '../components/charts';
import { COLORS } from '../theme';
import dayjs from 'dayjs';

const statusColor: Record<string, string> = { 有效: 'green', 衰减: 'gold', 失效: 'red' };

export default function Factors() {
  const [data, setData] = useState<FactorHealth[]>([]);
  const [loading, setLoading] = useState(true);
  const [date, setDate] = useState<string>('');

  useEffect(() => {
    const q = date ? `?date=${date}` : '';
    setLoading(true);
    api.get(`/factors/health${q}`).then((r) => setData(r.data)).finally(() => setLoading(false));
  }, [date]);

  if (loading) return <div className="page"><Spin /></div>;

  const columns = [
    { title: '因子', dataIndex: 'factor_name' },
    { title: 'IC', dataIndex: 'ic', render: (v: number) => v.toFixed(4) },
    { title: 'ICIR', dataIndex: 'icir', render: (v: number) => (isNaN(v) ? '-' : v.toFixed(2)) },
    { title: '分层收益', dataIndex: 'rank_return', render: (v: number) => (isNaN(v) ? '-' : v.toFixed(4)) },
    { title: '状态', dataIndex: 'status', render: (s: string) => <Tag color={statusColor[s]}>{s}</Tag> },
    { title: '权重', dataIndex: 'weight', render: (v: number) => v.toFixed(3) },
  ];

  const option = {
    grid: baseGrid,
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: data.map((d) => d.factor_name), ...AXIS_STYLE, axisLabel: { rotate: 45, color: 'rgba(255,255,255,0.65)' } },
    yAxis: { type: 'value', ...AXIS_STYLE },
    series: [
      { name: 'IC', type: 'bar', data: data.map((d) => +d.ic.toFixed(4)), itemStyle: { color: COLORS.factor } },
      { name: '权重', type: 'line', yAxisIndex: 0, data: data.map((d) => +d.weight.toFixed(3)), itemStyle: { color: COLORS.sentiment } },
    ],
  };

  return (
    <div className="page">
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
