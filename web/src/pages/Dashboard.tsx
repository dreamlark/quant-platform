import { useEffect, useState } from 'react';
import {
  Card, Col, Row, Table, Typography, Tag, Statistic, Empty,
  Button, Switch, Space, Progress, Alert, Tooltip,
} from 'antd';
import {
  DashboardSummary, Sector, UpdateStatus,
  triggerUpdate, getUpdateStatus, startAuto, stopAuto,
  apiGet, errMsg, isAxiosConflict,
} from '../api/client';
import { EChart, catAxis, valAxis, baseGrid, tooltipStyle, EChartsOption } from '../components/charts';
import { COLORS, tempColor } from '../theme';
import {
  PageHeader, PageLoading, dirTag, StatusTag, SentimentCard,
} from '../components/common';

const { Paragraph, Text } = Typography;

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
      setHint('已触发数据更新，进度见下方状态条');
      fetchStatus();
    } catch (e: unknown) {
      if (isAxiosConflict(e)) {
        setHint('已有更新任务在运行中，请稍候');
        fetchStatus();
      } else {
        setHint('触发更新失败：' + errMsg(e));
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

  return (
    <div className="page">
      <PageHeader title="每日简报" subtitle={`数据日期 ${data.date}`} />
      {error && (
        <Alert style={{ marginBottom: 16 }} type="error" showIcon message="看板数据加载失败" description={error} />
      )}
      {statusError && (
        <Alert style={{ marginBottom: 16 }} type="warning" showIcon message="状态接口异常" description={statusError} />
      )}

      {/* 运维控制卡片：立即更新 / 自动运行 / 状态进度 */}
      <Card className="metric-card" style={{ marginBottom: 16 }}>
        <Row align="middle" gutter={[16, 12]}>
          <Col>
            <Button type="primary" loading={triggering} onClick={handleUpdate}>
              立即更新
            </Button>
          </Col>
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
          <Col flex="auto">
            {status && status.total > 0 && (
              <Progress
                percent={pct}
                steps={status.total}
                size="small"
                status={
                  status.status === 'failed'
                    ? 'exception'
                    : status.status === 'success'
                      ? 'success'
                      : 'active'
                }
              />
            )}
          </Col>
        </Row>
        {status?.current_step && status.status === 'running' && (
          <div style={{ marginTop: 8 }}>
            <Text type="secondary">当前步骤：{status.current_step}（{status.progress}/{status.total}）</Text>
          </div>
        )}
        {status?.last_success_date && (
          <div style={{ marginTop: 4 }}>
            <Text type="secondary">最近成功更新目标日：{status.last_success_date}</Text>
          </div>
        )}
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
