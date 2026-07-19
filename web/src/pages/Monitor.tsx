import { useEffect, useRef, useState } from 'react';
import {
  Card, Row, Col, Table, Typography, Tag, Statistic, Empty, Progress, Tooltip, Alert, Button, Space,
} from 'antd';
import {
  MonitorOverview, DataStatus, FactorHealthSummary, ModelStatus, Freshness,
  RunLog,
  getMonitorOverview, getMonitorHistory, getRunLogs, errMsg,
} from '../api/client';
import {
  STATUS_META, FACTOR_STATUS_COLOR, BATCH_STEP_COLOR,
} from '../constants';
import {
  PageHeader, PageLoading, StatusTag, SentimentCard,
} from '../components/common';

const { Text } = Typography;

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
  const [logs, setLogs] = useState<RunLog[]>([]);
  const [autoScroll, setAutoScroll] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // ⚠️ 所有 hooks 必须在条件返回之前声明（React 规则）
  const logRef = useRef<HTMLDivElement>(null);

  const loadOverview = () =>
    getMonitorOverview()
      .then((r) => setOv(r.data))
      .catch((e) => setError(errMsg(e)))
      .finally(() => setLoading(false));
  const loadHistory = () =>
    getMonitorHistory(50)
      .then((r) => setRuns(r.data.runs as RunRow[]))
      .catch((e) => setError(errMsg(e)));

  const loadLogs = () =>
    getRunLogs()
      .then((r) => setLogs(r.data.logs || []))
      .catch(() => {});

  useEffect(() => {
    setError(null);
    loadOverview();
    loadHistory();
    loadLogs();
    const t1 = setInterval(loadOverview, 4000);
    const t2 = setInterval(loadHistory, 8000);
    const t3 = setInterval(loadLogs, 1500);  // 运行日志高频刷新
    return () => {
      clearInterval(t1);
      clearInterval(t2);
      clearInterval(t3);
    };
  }, []);

  // 日志自动滚动（hooks 必须在条件返回前）
  useEffect(() => {
    if (autoScroll && logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight;
    }
  }, [logs, autoScroll]);

  if (loading) return <PageLoading tip="正在加载运维总览…" />;

  const data: DataStatus | undefined = ov?.data;
  const factors: FactorHealthSummary | undefined = ov?.factors;
  const models: ModelStatus[] = ov?.models || [];
  const fresh: Freshness | undefined = ov?.freshness;
  const pipe = ov?.pipeline;
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
        <Col><StatusTag status={pipe?.status} /></Col>
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
          status={
            pipe?.status === 'failed'
              ? 'exception'
              : pipe?.status === 'success'
                ? 'success'
                : 'active'
          }
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
        <Table size="small" rowKey="run_id" pagination={false} columns={runColumns} dataSource={runs} scroll={{ x: 'max-content' }} />
      )}
    </Card>
  );

  // —— 实时运行日志面板 ——
  const LEVEL_COLOR: Record<string, string> = {
    info: '#8c8c8c',
    success: '#52c41a',
    warn: '#faad14',
    error: '#ff4d4f',
  };
  const logPanel = (
    <Card
      className="metric-card"
      title="实时运行日志"
      extra={
        <Space size="small">
          <Text type="secondary" style={{ fontSize: 12 }}>
            {logs.length > 0 ? `${logs.length} 条` : ''}
          </Text>
          <Button size="small" type={autoScroll ? 'primary' : 'default'} onClick={() => setAutoScroll(!autoScroll)}>
            {autoScroll ? '自动滚动' : '已暂停'}
          </Button>
          <Button size="small" onClick={() => setLogs([])}>清空</Button>
        </Space>
      }
    >
      {logs.length === 0 ? (
        <Empty description="暂无日志，点击「全量更新」后这里实时打印每步运行状态" />
      ) : (
        <div
          ref={logRef}
          style={{
            maxHeight: 360,
            overflowY: 'auto',
            background: 'rgba(0,0,0,0.25)',
            borderRadius: 6,
            padding: '8px 12px',
            fontFamily: 'Consolas, Monaco, "Courier New", monospace',
            fontSize: 12,
            lineHeight: 1.7,
          }}
        >
          {logs.map((l, i) => (
            <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
              <span style={{ color: '#666', flexShrink: 0 }}>{l.ts}</span>
              <span
                style={{
                  color: LEVEL_COLOR[l.level] || '#8c8c8c',
                  flexShrink: 0,
                  fontWeight: l.level === 'error' || l.level === 'success' ? 600 : 400,
                  minWidth: 48,
                }}
              >
                [{l.level.toUpperCase()}]
              </span>
              {l.step_label && (
                <span style={{ color: '#1890ff', flexShrink: 0 }}>{l.step_label}:</span>
              )}
              <span style={{ color: 'rgba(255,255,255,0.85)', wordBreak: 'break-all' }}>{l.message}</span>
            </div>
          ))}
        </div>
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
      <PageHeader title="运维监控" subtitle="数据状态 · 健康度 · 实时管线 · 运行历史" />
      {error && (
        <Alert style={{ marginBottom: 16 }} type="error" showIcon message="监控数据加载失败" description={error} />
      )}
      <Row gutter={[16, 16]}>
        <Col xs={24} md={8}>{dataCard}</Col>
        <Col xs={24} md={8}>{factorCard}</Col>
        <Col xs={24} md={8}>{pipelineCard}</Col>
      </Row>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>{modelCard}</Col>
        <Col xs={24} lg={10}>
          <Card className="metric-card" title="其他数据新鲜度">
            <div>信号库：{fresh?.signals_date || '-'}</div>
            <div style={{ marginTop: 6 }}>板块轮动：{fresh?.sector_date || '-'}</div>
            <div style={{ marginTop: 6 }}>每日简报：{fresh?.brief_date || '-'}</div>
          </Card>
        </Col>
      </Row>
      <Row gutter={[16, 16]}>
        <Col xs={24}>{batchRunCard}</Col>
      </Row>
      <Row gutter={[16, 16]}>
        <Col xs={24}><SentimentCard data={ov?.market_sentiment} /></Col>
      </Row>
      <Row gutter={[16, 16]}>
        <Col xs={24}>{historyCard}</Col>
      </Row>
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={24}>{logPanel}</Col>
      </Row>
    </div>
  );
}
