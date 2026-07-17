import { useEffect, useState } from 'react';
import {
  Card, Row, Col, Table, Typography, Tag, Spin, Statistic, Empty, Progress, Tooltip, Alert,
} from 'antd';
import {
  MonitorOverview, DataStatus, FactorHealthSummary, ModelStatus, Freshness,
  MarketSentimentView, getMonitorOverview, getMonitorHistory, errMsg,
} from '../api/client';
import {
  STATUS_META, FACTOR_STATUS_COLOR, REGIME_COLOR, REGIME_STATE_COLOR, SIGNAL_COLOR,
  BATCH_STEP_COLOR, subBar,
} from '../constants';

const { Title, Text } = Typography;

// 运行记录兼容两套 schema：手动运行(RunRecord) 与 批处理运行(BatchRunRecord)（P3-audit 修复）
interface RunRow {
  run_id: string;
  trigger: string;
  status: string;
  started_at: string | null;
  start_ts?: string | null;
  target_date?: string | null;
  date?: string | null;
  reached_step?: string;
  progress?: number;
  total?: number;
  duration_sec?: number;
  duration_s?: number;
  error?: string | null;
  kind?: string;
}

function fmtPct(v: number | null | undefined) {
  return v == null ? '-' : `${(v * 100).toFixed(1)}%`;
}

export default function Monitor() {
  const [ov, setOv] = useState<MonitorOverview | null>(null);
  const [runs, setRuns] = useState<RunRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadOverview = () =>
    getMonitorOverview()
      .then((r) => setOv(r.data))
      .catch((e) => setError(errMsg(e)))
      .finally(() => setLoading(false));
  const loadHistory = () =>
    getMonitorHistory(50)
      .then((r) => setRuns(r.data.runs as RunRow[]))
      .catch((e) => setError(errMsg(e)));

  useEffect(() => {
    setError(null);
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
    {
      title: '开始', dataIndex: 'started_at',
      render: (_: unknown, r: RunRow) => {
        const t = r.started_at || r.start_ts;
        return t ? t.replace('T', ' ') : '-';
      },
    },
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
    {
      title: '目标日', dataIndex: 'target_date',
      render: (_: unknown, r: RunRow) => r.target_date || r.date || '-',
    },
    {
      title: '到达步骤', dataIndex: 'reached_step',
      render: (_: unknown, r: RunRow) => r.reached_step ?? '-',
    },
    {
      title: '进度',
      render: (_: unknown, r: RunRow) => `${(r.progress ?? '-')}/${(r.total ?? '-')}`,
    },
    {
      title: '耗时', dataIndex: 'duration_sec',
      render: (_: unknown, r: RunRow) => `${(r.duration_sec ?? r.duration_s ?? '-')}s`,
    },
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

  const batch = ov?.batch_run;
  const batchRunCard = (
    <Card className="metric-card" title="批处理运行健康（盘后流水线）">
      {!batch || !batch.run ? (
        <Empty description="暂无批处理运行记录（运行一次盘后流水线后生成）" />
      ) : (
        <>
          <Row gutter={16} align="middle">
            <Col>
              <Tag color={batch.run.status === 'ok' ? 'green' : 'red'}>
                {batch.run.status === 'ok' ? '成功' : '失败'}
              </Tag>
            </Col>
            <Col>
              <Text type="secondary" style={{ fontSize: 12 }}>
                目标日 {batch.run.date} · 耗时 {batch.run.duration_s}s
                {batch.run.error ? ` · ${batch.run.error}` : ''}
              </Text>
            </Col>
          </Row>
          <div style={{ marginTop: 10 }}>
            {batch.steps.map((s, i) => (
              <Tag key={`${s.step}-${i}`} color={BATCH_STEP_COLOR[s.status] || 'default'} style={{ marginBottom: 4 }}>
                {s.step}{s.duration_s != null ? ` ${s.duration_s}s` : ''}{s.status === 'fail' ? ' ✗' : ' ✓'}
              </Tag>
            ))}
          </div>
        </>
      )}
    </Card>
  );

  return (
    <div className="page">
      <Title level={3}>运维监控</Title>
      {error && (
        <Alert style={{ marginBottom: 16 }} type="error" showIcon message="监控数据加载失败" description={error} />
      )}
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
        <Col span={24}>{batchRunCard}</Col>
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
