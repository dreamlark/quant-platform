import React, { useEffect, useState } from 'react';
import { Card, Table, Tag, Spin, Empty, DatePicker, Space } from 'antd';
import { api, Sector } from '../api/client';
import { EChart, AXIS_STYLE, baseGrid } from '../components/charts';
import { COLORS } from '../theme';
import dayjs from 'dayjs';

export default function Sectors() {
  const [data, setData] = useState<Sector[]>([]);
  const [loading, setLoading] = useState(true);
  const [date, setDate] = useState<string>('');

  useEffect(() => {
    const q = date ? `?date=${date}` : '';
    setLoading(true);
    api.get(`/sectors/rotation${q}`).then((r) => setData(r.data)).finally(() => setLoading(false));
  }, [date]);

  if (loading) return <div className="page"><Spin /></div>;

  const columns = [
    { title: '板块', dataIndex: 'sector_name' },
    { title: '代码', dataIndex: 'sector_code' },
    { title: '涨跌幅', dataIndex: 'change_pct', render: (v: number) => `${(v * 100).toFixed(2)}%` },
    { title: 'RS', dataIndex: 'rs', render: (v: number) => v.toFixed(3) },
    { title: '资金净流入', dataIndex: 'net_inflow', render: (v: number) => v.toFixed(0) },
    { title: '轮动', dataIndex: 'rotation_signal', render: (v: string) => <Tag color={v === '进攻' ? 'red' : v === '防御' ? 'green' : 'default'}>{v}</Tag> },
  ];

  const option = {
    grid: baseGrid,
    tooltip: { trigger: 'axis' },
    legend: { data: ['涨跌幅', 'RS'], textStyle: { color: 'rgba(255,255,255,0.65)' } },
    xAxis: { type: 'category', data: data.map((s) => s.sector_name), ...AXIS_STYLE, axisLabel: { rotate: 30, color: 'rgba(255,255,255,0.65)' } },
    yAxis: [
      { type: 'value', name: '涨跌幅%', ...AXIS_STYLE },
      { type: 'value', name: 'RS', ...AXIS_STYLE },
    ],
    series: [
      { name: '涨跌幅', type: 'bar', data: data.map((s) => +(s.change_pct * 100).toFixed(2)), itemStyle: { color: COLORS.factor } },
      { name: 'RS', type: 'line', yAxisIndex: 1, data: data.map((s) => +s.rs.toFixed(4)), itemStyle: { color: COLORS.predict } },
    ],
  };

  return (
    <div className="page">
      <Space style={{ marginBottom: 16 }}>
        <span>日期</span>
        <DatePicker onChange={(_, s) => setDate((Array.isArray(s) ? s[0] : s) || '')} defaultValue={date ? dayjs(date) : undefined} />
      </Space>
      {data.length === 0 ? (
        <Empty description="暂无板块数据" />
      ) : (
        <>
          <Card title="板块轮动" className="metric-card" style={{ marginBottom: 16 }}>
            <EChart option={option} height={340} />
          </Card>
          <Card title="板块强弱排名">
            <Table size="small" rowKey="sector_code" columns={columns} dataSource={data} pagination={false} />
          </Card>
        </>
      )}
    </div>
  );
}
