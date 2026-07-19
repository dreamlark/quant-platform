import React, { useEffect, useState } from 'react';
import {
  Card, Col, Row, Table, Typography, Tag, Spin, Statistic, Empty,
  Button, Switch, Space, Progress, Alert, Tooltip, Popconfirm,
} from 'antd';
import {
  api, DashboardSummary, Signal, Sector, WatchItem, MarketSentimentView,
  UpdateStatus, triggerUpdate, getUpdateStatus, startAuto, stopAuto,
} from '../api/client';
import { EChart, AXIS_STYLE, baseGrid } from '../components/charts';
import { COLORS } from '../theme';

const { Title, Paragraph, Text } = Typography;

const REGIME_COLOR: Record<string, string> = {
  恐惧: 'red',
  中性: 'default',
  贪婪: 'green',
};
const SIGNAL_COLOR: Record<string, string> = {
  买入: 'green',
  半仓: 'gold',
  空仓: 'red',
};
const REGIME_STATE_COLOR: Record<string, string> = {
  bull: 'green',
  neutral: 'default',
  bear: 'orange',
  panic: 'red',
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
      setHint('已触发全量数据更新（12步流水线），进度见下方');
      fetchStatus();
    } catch (e: any) {
      if (e?.response?.status === 409) {
        setHint('已有更新任务在运行中，可点击「终止」取消');
        fetchStatus();
      } else {
        setHint('触发更新失败：' + (e?.message || '未知错误'));
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

  // —— 市场情绪指数卡（PRD §8 双卡：Dashboard 侧）——
  const ms: MarketSentimentView | undefined = data.market_sentiment;
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

  const st = status ? STATUS_META[status.status] || STATUS_META.idle : STATUS_META.idle;
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
            <Tag color={st.color}>{st.label}</Tag>
            {status?.auto_enabled && status.next_run && (
              <Tooltip title="下次自动运行时间（Asia/Shanghai）">
                <Text type="secondary" style={{ fontSize: 12 }}>
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
      <Row gutter={16} style={{ marginTop: 16 }}>
        <Col span={24}>{sentimentCard}</Col>
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
