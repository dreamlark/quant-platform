import React, { useEffect, useState } from 'react';
import { Card, Col, Row, Table, Typography, Tag, Spin, Statistic, Empty } from 'antd';
import { api, DashboardSummary, Signal, Sector, WatchItem } from '../api/client';
import { EChart, AXIS_STYLE, baseGrid } from '../components/charts';
import { COLORS } from '../theme';

const { Title, Paragraph } = Typography;

function dirTag(d: number) {
  if (d === 1) return <Tag color="red">看多</Tag>;
  if (d === -1) return <Tag color="green">看空</Tag>;
  return <Tag>中性</Tag>;
}

export default function Dashboard() {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get('/dashboard/summary').then((r) => setData(r.data)).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="page"><Spin /></div>;
  if (!data) return <div className="page"><Empty description="暂无数据，请先运行数据链路" /></div>;

  const signalColumns = [
    { title: '代码', dataIndex: 'code' },
    { title: '方向', dataIndex: 'direction', render: (d: number) => dirTag(d) },
    { title: '置信度', dataIndex: 'confidence', render: (v: number) => v.toFixed(2) },
    { title: '来源', dataIndex: 'source_tags' },
  ];

  const sectorColumns = [
    { title: '板块', dataIndex: 'sector_name' },
    { title: '涨跌幅', dataIndex: 'change_pct', render: (v: number) => `${(v * 100).toFixed(2)}%` },
    { title: 'RS', dataIndex: 'rs', render: (v: number) => v.toFixed(3) },
    { title: '轮动', dataIndex: 'rotation_signal', render: (v: string) => <Tag>{v}</Tag> },
  ];

  const watchColumns = [
    { title: '代码', dataIndex: 'code' },
    { title: '名称', dataIndex: 'name' },
    { title: '现价', dataIndex: 'current_price', render: (v?: number) => (v ? v.toFixed(2) : '-') },
    { title: '盈亏%', dataIndex: 'pnl_pct', render: (v?: number) => (v == null ? '-' : <span style={{ color: v >= 0 ? COLORS.up : COLORS.down }}>{v.toFixed(2)}%</span>) },
    { title: '信号', dataIndex: 'direction', render: (d?: number) => (d == null ? '-' : dirTag(d)) },
  ];

  const sectorOption = {
    grid: baseGrid,
    tooltip: { trigger: 'axis' },
    xAxis: { type: 'category', data: data.sectors.map((s: Sector) => s.sector_name), ...AXIS_STYLE },
    yAxis: { type: 'value', ...AXIS_STYLE },
    series: [
      {
        type: 'bar',
        data: data.sectors.map((s: Sector) => +(s.change_pct * 100).toFixed(2)),
        itemStyle: { color: (p: any) => (p.value >= 0 ? COLORS.up : COLORS.down) },
      },
    ],
  };

  return (
    <div className="page">
      <Title level={3}>每日简报 · {data.date}</Title>
      <Row gutter={16}>
        <Col span={6}>
          <Card className="metric-card">
            <Statistic title="市场温度计" value={data.market_temperature} suffix="/100" />
          </Card>
        </Col>
        <Col span={18}>
          <Card className="metric-card" title="市场综述（LLM 研究观点）">
            {data.brief ? (
              <Paragraph style={{ whiteSpace: 'pre-wrap' }}>{data.brief}</Paragraph>
            ) : (
              <Empty description="简报未生成（无 LLM 密钥时仅展示信号）" />
            )}
          </Card>
        </Col>
      </Row>
      <Row gutter={16}>
        <Col span={14}>
          <Card className="metric-card" title="今日信号清单（按置信度）">
            <Table size="small" rowKey="code" columns={signalColumns} dataSource={data.top_signals} pagination={false} />
          </Card>
        </Col>
        <Col span={10}>
          <Card className="metric-card" title="自选股异动" >
            <Table size="small" rowKey="code" columns={watchColumns} dataSource={data.watchlist_alerts} pagination={false} />
          </Card>
        </Col>
      </Row>
      <Card title="板块热力">
        <EChart option={sectorOption} height={300} />
        <Table size="small" rowKey="sector_code" columns={sectorColumns} dataSource={data.sectors} pagination={false} />
      </Card>
    </div>
  );
}
