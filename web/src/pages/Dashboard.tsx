import React, { useEffect, useState } from 'react';
import {
  Card, Col, Row, Table, Typography, Tag, Spin, Statistic, Empty,
  Button, Switch, Space, Progress, Alert, Tooltip,
} from 'antd';
import {
  api, DashboardSummary, Signal, Sector, WatchItem,
  UpdateStatus, triggerUpdate, getUpdateStatus, startAuto, stopAuto,
} from '../api/client';
import { EChart, AXIS_STYLE, baseGrid } from '../components/charts';
import { COLORS } from '../theme';

const { Title, Paragraph, Text } = Typography;

function dirTag(d: number) {
  if (d === 1) return <Tag color="red">看多</Tag>;
  if (d === -1) return <Tag color="green">看空</Tag>;
  return <Tag>中性</Tag>;
}

const STATUS_META: Record<string, { color: string; label: string }> = {
  idle: { color: 'default', label: '空闲' },
  running: { color: 'processing', label: '更新中' },
  success: { color: 'success', label: '成功' },
  failed: { color: 'error', label: '失败' },
};

export default function Dashboard() {
  const [data, setData] = useState<DashboardSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [triggering, setTriggering] = useState(false);
  const [autoBusy, setAutoBusy] = useState(false);
  const [hint, setHint] = useState<string | null>(null);

  const fetchStatus = () =>
    getUpdateStatus()
      .then((r) => setStatus(r.data))
      .catch(() => {/* 状态接口异常不阻塞看板 */});

  useEffect(() => {
    api.get('/dashboard/summary').then((r) => setData(r.data)).finally(() => setLoading(false));
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
    } catch (e: any) {
      if (e?.response?.status === 409) {
        setHint('已有更新任务在运行中，请稍候');
        fetchStatus();
      } else {
        setHint('触发更新失败：' + (e?.message || '未知错误'));
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
    } catch (e: any) {
      setHint('切换自动运行失败：' + (e?.message || '未知错误'));
    } finally {
      setAutoBusy(false);
    }
  };

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

  const st = status ? STATUS_META[status.status] || STATUS_META.idle : STATUS_META.idle;
  const pct = status && status.total ? Math.round((status.progress / status.total) * 100) : 0;

  return (
    <div className="page">
      <Title level={3}>每日简报 · {data.date}</Title>

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
            <Tag color={st.color}>{st.label}</Tag>
            {status?.auto_enabled && status.next_run && (
              <Tooltip title="下次自动运行时间（Asia/Shanghai）">
                <Text type="secondary" style={{ fontSize: 12 }}>
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
                size={status.status === 'running' ? 'small' : 'small'}
                status={status.status === 'failed' ? 'exception' : status.status === 'success' ? 'success' : 'active'}
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
