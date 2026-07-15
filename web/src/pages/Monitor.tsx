import React, { useEffect, useState } from 'react';
import {
  Card, Row, Col, Table, Typography, Tag, Spin, Statistic, Empty, Progress, Tooltip,
} from 'antd';
import {
  api, MonitorOverview, RunRecord, DataStatus, FactorHealthSummary, ModelStatus, Freshness,
  MarketSentimentView,
  getMonitorOverview, getMonitorHistory,
} from '../api/client';
import { COLORS } from '../theme';

const { Title, Text } = Typography;

const STATUS_META: Record<string, { color: string; label: string }> = {
  idle: { color: 'default', label: '空闲' },
  running: { color: 'processing', label: '更新中' },
  success: { color: 'success', label: '成功' },
  failed: { color: 'error', label: '失败' },
};

const FACTOR_STATUS_COLOR: Record<string, string> = {
  有效: 'green',
  衰减: 'gold',
  失效: 'red',
};

const REGIME_COLOR: Record<string, string> = {
  恐惧: 'red',
  中性: 'default',
  贪婪: 'green',
};
const REGIME_STATE_COLOR: Record<string, string> = {
  bull: 'green',
  neutral: 'default',
  bear: 'orange',
  panic: 'red',
};
const SIGNAL_COLOR: Record<string, string> = {
  买入: 'green',
  半仓: 'gold',
  空仓: 'red',
};

function subBar(label: string, v: number | null | undefined) {
  if (v == null) return null;
  return (
    <div style={{ marginTop: 4 }}>
      <Text type="secondary" style={{ fontSize: 12 }}>{label}：{v.toFixed(1)}</Text>
      <Progress
        percent={Math.round(v)}
        size="small"
        showInfo={false}
        strokeColor={v >= 50 ? COLORS.up : COLORS.down}
      />
    </div>
  );
}

function fmtPct(v: number | null | undefined) {
  return v == null ? '-' : `${(v * 100).toFixed(1)}%`;
}

export default function Monitor() {
  const [ov, setOv] = useState<MonitorOverview | null>(null);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [loading, setLoading] = useState(true);

  const loadOverview = () =>
    getMonitorOverview()
      .then((r) => setOv(r.data))
      .catch(() => {/* 观测层降级不影响页面 */})
      .finally(() => setLoading(false));
  const loadHistory = () =>
    getMonitorHistory(50)
      .then((r) => setRuns(r.data.runs))
      .catch(() => {});

  useEffect(() => {
    loadOverview();
    loadHistory();
    const t1 = setInterval(loadOverview, 4000);
    const t2 = setInterval(loadHistory, 8000);
    return () => {
      clearInterval(t1);
      clearInterval(t2);
    };
  }, []);

  if (loading) return <div className="page"><Spin /></div>;

  const data: DataStatus | undefined = ov?.data;
  const factors: FactorHealthSummary | undefined = ov?.factors;
  const models: ModelStatus[] = ov?.models || [];
  const fresh: Freshness | undefined = ov?.freshness;
  const pipe = ov?.pipeline;
  const st = pipe ? STATUS_META[pipe.status] || STATUS_META.idle : STATUS_META.idle;
  const pct = pipe && pipe.total ? Math.round((pipe.progress / pipe.total) * 100) : 0;

  // —— 数据状态卡 ——
  const dataCard = (
    <Card className="metric-card" title="数据状态（行情库）">
      {data?.error ? (
        <Text type="danger">{data.error}</Text>
      ) : (
        <>
          <Statistic title="最新交易日" value={data?.latest_date || '-'} />
          <div style={{ marginTop: 8 }}>
            <Tag color={data?.is_stale ? 'red' : 'green'}>
              {data?.is_stale ? '已过期' : '新鲜'}
            </Tag>
            {data?.days_since != null && (
              <Text type="secondary">距今 {data.days_since} 天</Text>
            )}
          </div>
          <Row gutter={16} style={{ marginTop: 8 }}>
            <Col span={12}><Statistic title="股票数" value={data?.stock_count ?? '-'} /></Col>
            <Col span={12}><Statistic title="可投资域" value={data?.universe_count ?? '-'} /></Col>
          </Row>
        </>
      )}
    </Card>
  );

  // —— 因子健康卡 ——
  const factorCard = (
    <Card className="metric-card" title="因子健康度">
      {factors?.error ? (
        <Text type="danger">{factors.error}</Text>
      ) : (
        <>
          <div>
            <Text type="secondary">体检日 {factors?.latest_date || '-'} · 共 {factors?.total ?? 0} 因子</Text>
          </div>
          <div style={{ marginTop: 8 }}>
            {factors?.by_status &&
              Object.entries(factors.by_status).map(([s, c]) => (
                <Tag key={s} color={FACTOR_STATUS_COLOR[s] || 'default'}>
                  {s} {c}
                </Tag>
              ))}
          </div>
          <div style={{ marginTop: 8 }}>
            <Statistic title="平均 ICIR" value={factors?.avg_icir ?? '-'} precision={3} />
          </div>
        </>
      )}
    </Card>
  );

  // —— 模型状态卡 ——
  const modelColumns = [
    {
      title: '模型', dataIndex: 'model_name',
      render: (v: string) => (v === 'kronos' ? <Tag color="cyan">Kronos</Tag> : v),
    },
    { title: '方向准确率', dataIndex: 'dir_acc', render: (v: number | null) => fmtPct(v) },
    { title: '覆盖股票', dataIndex: 'coverage_count', render: (v: number | null) => (v == null ? '-' : v) },
    { title: '日期', dataIndex: 'date' },
  ];
  const modelCard = (
    <Card className="metric-card" title="模型状态（预测源）">
      {models.length === 0 ? (
        <Empty description="暂无模型健康记录" />
      ) : (
        <Table
          size="small" rowKey="model_name" pagination={false}
          columns={modelColumns} dataSource={models}
        />
      )}
    </Card>
  );

  // —— 管线运行卡（实时）——
  const pipelineCard = (
    <Card className="metric-card" title="管线运行（实时）">
      <Row align="middle" gutter={[12, 8]}>
        <Col><Tag color={st.color}>{st.label}</Tag></Col>
        <Col>
          {ov?.auto.enabled && ov.auto.next_run && (
            <Tooltip title="下次自动运行（Asia/Shanghai）">
              <Text type="secondary" style={{ fontSize: 12 }}>自动运行 · 下次 {ov.auto.next_run}</Text>
            </Tooltip>
          )}
          {!ov?.auto.enabled && <Text type="secondary" style={{ fontSize: 12 }}>自动运行：关</Text>}
        </Col>
      </Row>
      <div style={{ marginTop: 8 }}>
        <Progress
          percent={pct}
          steps={pipe?.total || 11}
          size="small"
          status={pipe?.status === 'failed' ? 'exception' : pipe?.status === 'success' ? 'success' : 'active'}
        />
      </div>
      {pipe?.current_step && pipe.status === 'running' && (
        <div style={{ marginTop: 4 }}>
          <Text type="secondary">当前步骤：{pipe.current_step}（{pipe.progress}/{pipe.total}）</Text>
        </div>
      )}
      {pipe?.last_success_date && (
        <div style={{ marginTop: 4 }}>
          <Text type="secondary">最近成功目标日：{pipe.last_success_date}</Text>
        </div>
      )}
      {pipe?.status === 'failed' && pipe.last_error && (
        <div style={{ marginTop: 4 }}>
          <Text type="danger" style={{ wordBreak: 'break-all' }}>{pipe.last_error}</Text>
        </div>
      )}
    </Card>
  );

  // —— 运行记录卡 ——
  const runColumns = [
    { title: '开始', dataIndex: 'started_at', render: (v: string) => v.replace('T', ' ') },
    {
      title: '触发', dataIndex: 'trigger',
      render: (v: string) => (v === 'auto' ? <Tag>自动</Tag> : <Tag color="blue">手动</Tag>),
    },
    {
      title: '状态', dataIndex: 'status',
      render: (v: string) => {
        const m = STATUS_META[v] || STATUS_META.idle;
        return <Tag color={m.color}>{m.label}</Tag>;
      },
    },
    { title: '目标日', dataIndex: 'target_date', render: (v: string | null) => v || '-' },
    { title: '到达步骤', dataIndex: 'reached_step' },
    { title: '进度', render: (_: any, r: RunRecord) => `${r.progress}/${r.total}` },
    { title: '耗时', dataIndex: 'duration_sec', render: (v: number) => `${v}s` },
    {
      title: '错误', dataIndex: 'error',
      render: (v: string | null) =>
        v ? (
          <Tooltip title={v}><Text type="danger" ellipsis style={{ maxWidth: 160, display: 'inline-block' }}>{v}</Text></Tooltip>
        ) : (
          '-'
        ),
    },
  ];
  const historyCard = (
    <Card className="metric-card" title={`运行记录（最近 ${runs.length} 次）`}>
      {runs.length === 0 ? (
        <Empty description="暂无运行记录，点「立即更新」后会出现在这里" />
      ) : (
        <Table size="small" rowKey="run_id" pagination={false} columns={runColumns} dataSource={runs} />
      )}
    </Card>
  );

  const ms: MarketSentimentView | undefined = ov?.market_sentiment;
  const sentimentCard = (
    <Card className="metric-card" title="市场情绪指数（T1/T2/T3）">
      {!ms || !ms.available ? (
        <Text type="secondary">
          {ms?.error ? ms.error : '暂无市场情绪数据（运行一次盘后流水线后生成）'}
        </Text>
      ) : (
        <>
          <Row gutter={16} align="middle">
            <Col span={10}>
              <Statistic title="综合情绪指数" value={ms.index_value ?? '-'} precision={1} />
            </Col>
            <Col span={14}>
              <div>
                <Tag color={REGIME_COLOR[ms.regime || ''] || 'default'}>{ms.regime || '-'}</Tag>
                <Tag color={SIGNAL_COLOR[ms.signal || ''] || 'default'}>{ms.signal || '-'}</Tag>
              </div>
              <div style={{ marginTop: 6 }}>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  温度计 {ms.thermometer ?? '-'} · GSISI {ms.gsisi ?? '-'}
                </Text>
              </div>
              <div style={{ marginTop: 6 }}>
                <Tag color={REGIME_STATE_COLOR[ms.regime_state || ''] || 'default'}>
                  状态 {ms.regime_state || '-'}
                </Tag>
                <Text type="secondary" style={{ fontSize: 12 }}>
                  置信缩放 ×{(ms.regime_scale ?? 1).toFixed(2)}
                </Text>
              </div>
            </Col>
          </Row>
          <div style={{ marginTop: 8 }}>
            {subBar('量能分', ms.sub_volume)}
            {subBar('价格分', ms.sub_price)}
            {subBar('资金分', ms.sub_money)}
            {subBar('估值分', ms.sub_valuation)}
            {subBar('风险溢价分', ms.sub_riskpremium)}
          </div>
          <div style={{ marginTop: 6 }}>
            <Text type="secondary" style={{ fontSize: 12 }}>更新日 {ms.latest_date}</Text>
          </div>
        </>
      )}
    </Card>
  );

  return (
    <div className="page">
      <Title level={3}>运维监控</Title>
      <Row gutter={16}>
        <Col span={8}>{dataCard}</Col>
        <Col span={8}>{factorCard}</Col>
        <Col span={8}>{pipelineCard}</Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={14}>{modelCard}</Col>
        <Col span={10}>
          <Card className="metric-card" title="其他数据新鲜度">
            <div>信号库：{fresh?.signals_date || '-'}</div>
            <div style={{ marginTop: 6 }}>板块轮动：{fresh?.sector_date || '-'}</div>
            <div style={{ marginTop: 6 }}>每日简报：{fresh?.brief_date || '-'}</div>
          </Card>
        </Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={24}>{sentimentCard}</Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={24}>{historyCard}</Col>
      </Row>
    </div>
  );
}
