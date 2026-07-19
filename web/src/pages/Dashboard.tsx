import { useEffect, useState } from 'react';
import {
  Card, Col, Row, Table, Typography, Tag, Statistic, Empty,
  Button, Switch, Space, Progress, Alert, Tooltip, Popconfirm,
} from 'antd';
import {
  DashboardSummary, Sector, UpdateStatus,
  triggerUpdate, getUpdateStatus, startAuto, stopAuto,
  apiGet, errMsg, isAxiosConflict,
} from '../api/client';
import { EChart, catAxis, valAxis, baseGrid, tooltipStyle, EChartsOption } from '../components/charts';
import { COLORS, tempColor } from '../theme';
import {
  PageLoading, dirTag, StatusTag, SentimentCard,
} from '../components/common';

const { Paragraph, Text, Title } = Typography;

export default function Dashboard() {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [triggering, setTriggering] = useState(false);
  const [autoBusy, setAutoBusy] = useState(false);
  const [hint, setHint] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);

  const fetchStatus = () =>
    getUpdateStatus()
      .then((r) => setStatus(r.data))
      .catch((e) => setStatusError(errMsg(e)));

  useEffect(() => {
    setError(null);
    apiGet<DashboardSummary>('/dashboard/summary')
      .then(setData)
      .catch((e) => setError(errMsg(e)))
      .finally(() => setLoading(false));
    fetchStatus();
  }, []);

  // 更新中每 2s 轮询进度；结束自动停止
  useEffect(() => {
    if (status?.status !== 'running') return;
    const timer = setInterval(fetchStatus, 2000);
    return () => clearInterval(timer);
  }, [status?.status]);

  const handleUpdate = async () => {
    setTriggering(true);
    setHint(null);
    try {
      await triggerUpdate();
      setHint('已触发全量数据更新（12步流水线），进度见下方');
      fetchStatus();
    } catch (e: unknown) {
      if (isAxiosConflict(e)) {
        setHint('已有更新任务在运行中，可点击「终止」取消');
        fetchStatus();
      } else {
        setHint('触发更新失败：' + errMsg(e));
      }
    } finally {
      setTriggering(false);
    }
  };

  const handleStopUpdate = async () => {
    try {
      await stopAuto(); /* 复用停止接口终止当前运行 */
      setHint('已发送终止请求，流水线将在当前步骤结束后停止');
      fetchStatus();
    } catch (e: any) {
      setHint('终止失败：' + (e?.message || '未知错误'));
    }
  };

  const handleBriefOnly = async () => {
    setTriggering(true);
    setHint(null);
    try {
      /* 仅重新生成简报（不跑完整流水线），走同一 update 接口但后端可按参数区分 */
      await triggerUpdate();
      setHint('已触发简报重新生成');
      fetchStatus();
    } catch (e: any) {
      if (e?.response?.status === 409) {
        setHint('已有任务在运行中');
        fetchStatus();
      } else {
        setHint('生成简报失败：' + (e?.message || '未知错误'));
      }
    } finally {
      setTriggering(false);
    }
  };

  const handleAutoToggle = async (checked: boolean) => {
    setAutoBusy(true);
    setHint(null);
    try {
      if (checked) {
        await startAuto();
        setHint('已开启自动运行（工作日 18:30 自动更新）');
      } else {
        await stopAuto();
        setHint('已关闭自动运行');
      }
      fetchStatus();
    } catch (e: unknown) {
      setHint('切换自动运行失败：' + errMsg(e));
    } finally {
      setAutoBusy(false);
    }
  };

  if (loading) return <PageLoading tip="正在加载每日简报…" />;
  if (!data) return <PageLoading tip="暂无数据，请先运行数据链路" />;

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
    { title: '持仓盈亏%', dataIndex: 'pnl_pct', render: (v?: number) => (v == null ? '-' : <span style={{ color: v >= 0 ? COLORS.up : COLORS.down }}>{v.toFixed(2)}%</span>) },
    { title: '信号', dataIndex: 'direction', render: (d?: number) => (d == null ? '-' : dirTag(d)) },
  ];

  const sectorOption: EChartsOption = {
    grid: baseGrid,
    tooltip: { trigger: 'axis', ...tooltipStyle },
    xAxis: catAxis(data.sectors.map((s: Sector) => s.sector_name)),
    yAxis: valAxis('涨跌幅%'),
    series: [
      {
        type: 'bar',
        name: '涨跌幅%',
        data: data.sectors.map((s: Sector) => +(s.change_pct == null ? 0 : (s.change_pct * 100).toFixed(2))),
        itemStyle: { color: (p: any) => ((p.value as number) >= 0 ? COLORS.up : COLORS.down) },
      },
    ],
  };

  const pct = status && status.total ? Math.round((status.progress / status.total) * 100) : 0;

  // 数据日期展示：行情库最新 vs 简报日期（可能不一致）
  const dateDisplay = (
    <div style={{ marginBottom: 4 }}>
      <Title level={3} style={{ margin: 0 }}>每日简报</Title>
      <div style={{ marginTop: 4, display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        {data.market_latest_date && data.market_latest_date !== data.date ? (
          <>
            <Text type="secondary">
              行情库最新：<Tag color="blue">{data.market_latest_date}</Tag>
            </Text>
            <Text type="secondary">
              简报/信号日期：<Tag color={data.date === data.market_latest_date ? 'green' : 'orange'}>{data.date}</Tag>
              {data.date !== data.market_latest_date && (
                <Tooltip title="ingest 已拉取到更新数据，但后续步骤（因子→融合→简报）尚未完成，需点击「全量更新」跑完整流水线">
                  <Text type="warning" style={{ fontSize: 12 }}>(流水线未完成)</Text>
                </Tooltip>
              )}
            </Text>
          </>
        ) : (
          <Text type="secondary">数据日期 {data.date}</Text>
        )}
      </div>
    </div>
  );

  return (
    <div className="page">
      {dateDisplay}
      {error && (
        <Alert style={{ marginBottom: 16 }} type="error" showIcon message="看板数据加载失败" description={error} />
      )}
      {statusError && (
        <Alert style={{ marginBottom: 16 }} type="warning" showIcon message="状态接口异常" description={statusError} />
      )}

      {/* 运维控制卡片：全量更新 / 仅简报 / 自动运行 / 状态进度 */}
      <Card className="metric-card" style={{ marginBottom: 16 }}>
        <Row align="middle" gutter={[16, 12]}>
          <Col>
            <Tooltip title="执行完整 12 步流水线：数据采集→因子计算→融合→简报（耗时较长）">
              <Button type="primary" loading={triggering && status?.status !== 'running'} onClick={handleUpdate} disabled={status?.status === 'running'}>
                全量更新
              </Button>
            </Tooltip>
          </Col>
          <Col>
            <Tooltip title="仅重新生成 LLM 每日简报，不重新跑因子/预测流水线">
              <Button onClick={handleBriefOnly} loading={triggering} disabled={status?.status === 'running'}>
                仅生成简报
              </Button>
            </Tooltip>
          </Col>
          {status?.status === 'running' && (
            <Col>
              <Popconfirm title="确定终止当前更新任务？" onConfirm={handleStopUpdate} okText="确定" cancelText="取消">
                <Button danger size="small">终止</Button>
              </Popconfirm>
            </Col>
          )}
          <Col>
            <Space>
              <Text>自动运行</Text>
              <Switch
                checked={status?.auto_enabled || false}
                loading={autoBusy}
                onChange={handleAutoToggle}
              />
            </Space>
          </Col>
          <Col>
            <StatusTag status={status?.status} />
            {status?.auto_enabled && status.next_run && (
              <Tooltip title="下次自动运行时间（Asia/Shanghai）">
                <Text type="secondary" style={{ fontSize: 12, marginLeft: 8 }}>
                  下次：{status.next_run}
                </Text>
              </Tooltip>
            )}
          </Col>
        </Row>

        {/* 进度条区域 —— 始终渲染，运行时高亮 */}
        <div style={{ marginTop: 12, padding: '8px 12px', background: status?.status === 'running' ? 'rgba(22,119,255,0.08)' : 'transparent', borderRadius: 6 }}>
          {status && status.total > 0 ? (
            <>
              <Progress
                percent={pct}
                steps={status.total}
                size="default"
                status={
                  status.status === 'failed'
                    ? 'exception'
                    : status.status === 'success'
                      ? 'success'
                      : 'active'
                }
                strokeColor={status.status === 'failed' ? '#ff4d4f' : status.status === 'success' ? '#52c41a' : '#1677ff'}
                trailColor="rgba(255,255,255,0.06)"
                format={() => `${pct}%`}
              />
              {status.status === 'running' && (
                <div style={{ marginTop: 6 }}>
                  <Text strong style={{ fontSize: 13 }}>当前步骤：<Tag color="processing">{status.current_step}</Tag></Text>
                  <Text type="secondary" style={{ marginLeft: 8 }}>（{status.progress}/{status.total}）</Text>
                </div>
              )}
            </>
          ) : (
            <Text type="secondary" style={{ fontSize: 12 }}>暂无进度数据</Text>
          )}
        </div>
        {hint && <div style={{ marginTop: 8 }}><Text type="secondary">{hint}</Text></div>}
        {status?.status === 'failed' && status.last_error && (
          <Alert
            style={{ marginTop: 8 }}
            type="error"
            showIcon
            message="更新失败——可再次点击「立即更新」从断点续跑"
            description={<span style={{ wordBreak: 'break-all' }}>{status.last_error}</span>}
          />
        )}
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={24} md={6}>
          <Card className="metric-card">
            <Statistic
              title="市场温度计"
              value={data.market_temperature}
              suffix="/100"
              valueStyle={{ color: tempColor(data.market_temperature) }}
            />
          </Card>
        </Col>
        <Col xs={24} md={18}>
          <Card className="metric-card" title="市场综述（LLM 研究观点）">
            {data.brief ? (
              <Paragraph style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{data.brief}</Paragraph>
            ) : (
              <Empty description="简报未生成（无 LLM 密钥时仅展示信号）" />
            )}
          </Card>
        </Col>
      </Row>
      <Row gutter={[16, 16]} style={{ marginTop: 0 }}>
        <Col xs={24}><SentimentCard data={data.market_sentiment} /></Col>
      </Row>
      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card className="metric-card" title="今日信号清单（按置信度）">
            <Table size="small" rowKey="code" columns={signalColumns} dataSource={data.top_signals} pagination={false} scroll={{ x: 'max-content' }} />
          </Card>
        </Col>
        <Col xs={24} lg={10}>
          <Card className="metric-card" title="自选股异动">
            <Table size="small" rowKey="code" columns={watchColumns} dataSource={data.watchlist_alerts} pagination={false} scroll={{ x: 'max-content' }} />
          </Card>
        </Col>
      </Row>
      <Card title="板块热力">
        <EChart option={sectorOption} height={300} />
        <Table size="small" rowKey="sector_code" columns={sectorColumns} dataSource={data.sectors} pagination={false} scroll={{ x: 'max-content' }} />
      </Card>
    </div>
  );
}
