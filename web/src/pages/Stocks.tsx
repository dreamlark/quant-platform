import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { Card, Table, Tag, Empty, Row, Col, Statistic, AutoComplete, Alert } from 'antd';
import { SignalDetail, apiGet, errMsg } from '../api/client';
import { EChart, catAxis, valAxis, baseGrid, tooltipStyle, EChartsOption } from '../components/charts';
import { COLORS } from '../theme';
import { PageHeader, PageLoading } from '../components/common';

function dirText(d: number) {
  return d === 1 ? '看多' : d === -1 ? '看空' : '中性';
}

interface StockBar {
  date: string;
  open: number;
  close: number;
  low: number;
  high: number;
}

export default function Stocks() {
  // 支持深链 /stocks/:code（P3-audit 修复：原仅能经搜索选择，直接访问个股页为空）
  const { code: paramCode } = useParams();
  const [options, setOptions] = useState<{ value: string; label: string }[]>([]);
  const [code, setCode] = useState<string>(paramCode || '');
  useEffect(() => { setCode(paramCode || ''); }, [paramCode]);
  const [detail, setDetail] = useState<SignalDetail | null>(null);
  const [bars, setBars] = useState<StockBar[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSearch = async (q: string) => {
    if (!q) return;
    const r = await apiGet<{ code: string; name: string }[]>('/stocks/search', { params: { q } });
    setOptions(r.map((x) => ({ value: x.code, label: `${x.code} ${x.name}` })));
  };

  useEffect(() => {
    if (!code) return;
    setLoading(true);
    setError(null);
    Promise.all([
      apiGet<SignalDetail>(`/stocks/${code}`),
      apiGet<StockBar[]>(`/stocks/${code}/bars`),
    ])
      .then(([d, b]) => {
        setDetail(d);
        setBars(b);
      })
      .catch((e) => setError(errMsg(e)))
      .finally(() => setLoading(false));
  }, [code]);

  if (loading) return <PageLoading tip="正在加载个股信号…" />;

  const contribOption: EChartsOption | null = detail
    ? {
        grid: baseGrid,
        tooltip: { trigger: 'axis', ...tooltipStyle },
        xAxis: catAxis(['因子', '技术', '情绪', '预测']),
        yAxis: valAxis(),
        series: [
          {
            type: 'bar',
            data: [
              +detail.factor_contrib.toFixed(3),
              +detail.tech_contrib.toFixed(3),
              +detail.sentiment_contrib.toFixed(3),
              +detail.predict_contrib.toFixed(3),
            ],
            itemStyle: {
              color: (p: any) => [COLORS.factor, COLORS.tech, COLORS.sentiment, COLORS.predict][p.dataIndex as number],
            },
          },
        ],
      }
    : null;

  const candleOption: EChartsOption | null = bars.length
    ? {
        grid: { left: 50, right: 16, top: 20, bottom: 40, containLabel: true },
        tooltip: { trigger: 'axis', ...tooltipStyle },
        xAxis: catAxis(bars.map((b) => b.date)),
        yAxis: { ...valAxis('价格'), scale: true },
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
    { title: '值', dataIndex: 'value', render: (v: number | null | undefined) => (v == null || isNaN(v) ? '-' : v.toFixed(4)) },
  ];

  return (
    <div className="page">
      <PageHeader title="股票信号拆解" subtitle="四源贡献 · K 线 · 因子明细" />
      {error && (
        <Alert style={{ marginBottom: 16 }} type="error" showIcon message="个股数据加载失败" description={error} />
      )}
      <AutoComplete
        style={{ width: 320, marginBottom: 16 }}
        options={options}
        value={code}
        onSearch={onSearch}
        onSelect={(v) => setCode(v)}
        onChange={(v) => setCode(v)}
        placeholder="搜索代码/名称，如 600519"
      />
      {!code && <Empty description="请选择标的查看信号拆解" />}
      {detail && (
        <>
          <Row gutter={[16, 16]}>
            <Col xs={24} sm={6}>
              <Card className="metric-card">
                <Statistic title="方向" value={dirText(detail.direction)} />
              </Card>
            </Col>
            <Col xs={24} sm={6}>
              <Card className="metric-card">
                <Statistic title="置信度（信号层）" value={detail.confidence.toFixed(2)} />
              </Card>
            </Col>
            <Col xs={24} sm={12}>
              <Card className="metric-card" title="来源标签">
                <Tag color="blue">{detail.source_tags}</Tag>
              </Card>
            </Col>
          </Row>
          <Row gutter={[16, 16]}>
            <Col xs={24} lg={10}>
              <Card title="四源贡献拆解" className="metric-card">
                {contribOption && <EChart option={contribOption} height={280} />}
              </Card>
            </Col>
            <Col xs={24} lg={14}>
              <Card title="K 线（前复权·仅展示）" className="metric-card">
                {candleOption && <EChart option={candleOption} height={280} />}
              </Card>
            </Col>
          </Row>
          <Card title="因子贡献明细">
            <Table size="small" rowKey="factor_name" columns={factorColumns} dataSource={detail.factor_detail} pagination={false} scroll={{ x: 'max-content' }} />
          </Card>
        </>
      )}
    </div>
  );
}
