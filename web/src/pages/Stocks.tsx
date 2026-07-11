import React, { useEffect, useState } from 'react';
import { Card, Input, Table, Tag, Spin, Empty, Row, Col, Statistic, AutoComplete, Typography } from 'antd';
import { api, SignalDetail } from '../api/client';
import { EChart, AXIS_STYLE, baseGrid } from '../components/charts';
import { COLORS } from '../theme';

const { Title } = Typography;

function dirText(d: number) {
  return d === 1 ? '看多' : d === -1 ? '看空' : '中性';
}

export default function Stocks() {
  const [options, setOptions] = useState<{ value: string; label: string }[]>([]);
  const [code, setCode] = useState<string>('');
  const [detail, setDetail] = useState<SignalDetail | null>(null);
  const [bars, setBars] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  const onSearch = async (q: string) => {
    if (!q) return;
    const r = await api.get(`/stocks/search?q=${q}`);
    setOptions(r.data.map((x: any) => ({ value: x.code, label: `${x.code} ${x.name}` })));
  };

  useEffect(() => {
    if (!code) return;
    setLoading(true);
    Promise.all([api.get(`/stocks/${code}`), api.get(`/stocks/${code}/bars`)])
      .then(([d, b]) => {
        setDetail(d.data);
        setBars(b.data);
      })
      .finally(() => setLoading(false));
  }, [code]);

  const contribOption = detail
    ? {
        grid: baseGrid,
        tooltip: { trigger: 'axis' },
        xAxis: { type: 'category', data: ['因子', '技术', '情绪', '预测'], ...AXIS_STYLE },
        yAxis: { type: 'value', ...AXIS_STYLE },
        series: [
          {
            type: 'bar',
            data: [
              +detail.factor_contrib.toFixed(3),
              +detail.tech_contrib.toFixed(3),
              +detail.sentiment_contrib.toFixed(3),
              +detail.predict_contrib.toFixed(3),
            ],
            itemStyle: { color: (p: any) => [COLORS.factor, COLORS.tech, COLORS.sentiment, COLORS.predict][p.dataIndex] },
          },
        ],
      }
    : null;

  const candleOption = bars.length
    ? {
        grid: { left: 50, right: 16, top: 20, bottom: 40 },
        tooltip: { trigger: 'axis' },
        xAxis: { type: 'category', data: bars.map((b) => b.date), ...AXIS_STYLE },
        yAxis: { type: 'value', scale: true, ...AXIS_STYLE },
        series: [
          {
            type: 'candlestick',
            data: bars.map((b) => [b.open, b.close, b.low, b.high]),
            itemStyle: { color: COLORS.up, color0: COLORS.down, borderColor: COLORS.up, borderColor0: COLORS.down },
          },
        ],
      }
    : null;

  const factorColumns = [
    { title: '因子', dataIndex: 'factor_name' },
    { title: '值', dataIndex: 'value', render: (v: number) => (isNaN(v) ? '-' : v.toFixed(4)) },
  ];

  return (
    <div className="page">
      <Title level={3}>股票信号拆解</Title>
      <AutoComplete
        style={{ width: 320, marginBottom: 16 }}
        options={options}
        onSearch={onSearch}
        onSelect={(v) => setCode(v)}
        placeholder="搜索代码/名称，如 600519"
      />
      {loading && <Spin />}
      {!code && <Empty description="请选择标的查看信号拆解" />}
      {detail && (
        <>
          <Row gutter={16}>
            <Col span={6}>
              <Card className="metric-card">
                <Statistic title="方向" value={dirText(detail.direction)} />
              </Card>
            </Col>
            <Col span={6}>
              <Card className="metric-card">
                <Statistic title="置信度（信号层）" value={detail.confidence.toFixed(2)} />
              </Card>
            </Col>
            <Col span={12}>
              <Card className="metric-card" title="来源标签">
                <Tag color="blue">{detail.source_tags}</Tag>
              </Card>
            </Col>
          </Row>
          <Row gutter={16}>
            <Col span={10}>
              <Card title="四源贡献拆解" className="metric-card">
                {contribOption && <EChart option={contribOption} height={280} />}
              </Card>
            </Col>
            <Col span={14}>
              <Card title="K 线（前复权·仅展示）" className="metric-card">
                {candleOption && <EChart option={candleOption} height={280} />}
              </Card>
            </Col>
          </Row>
          <Card title="因子贡献明细">
            <Table size="small" rowKey="factor_name" columns={factorColumns} dataSource={detail.factor_detail} pagination={false} />
          </Card>
        </>
      )}
    </div>
  );
}
