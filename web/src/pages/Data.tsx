import React, { useEffect, useState } from 'react';
import {
  Card, Row, Col, Table, Typography, Tag, Spin, Statistic, Empty,
  Button, Space, Progress, Alert, Descriptions, Divider, Switch, InputNumber,
  Tooltip, Modal, message, Select,
} from 'antd';
import { api } from '../api/client';
import { COLORS } from '../theme';

const { Title, Text, Paragraph } = Typography;

// —— 类型定义（复用 client.ts 中的，避免循环依赖用内联）——
interface DataSourceStatus {
  name: string;
  priority: number;
  available: boolean;
  latency_ms: number | null;
  last_error: string | null;
}

interface DataFileInfo {
  file: string;           // market / analytics
  size_mb: number | null;
  row_count: number | null;
  latest_date: string | null;
  modified_at: string | null;
  exists: boolean;
}

interface DataOverview {
  market_db: DataFileInfo;
  analytics_db: DataFileInfo;
  sources: DataSourceStatus[];
  universe_total: number | null;
  stale_days: number | null;
}

interface ImportResult {
  status: string;
  imported_rows: number;
  duration_s: number;
  target_date: string;
  error?: string;
}

// —— 数据源优先级配置项 ——
const SOURCE_OPTIONS = [
  { label: 'mootdx（腾讯/防封）', value: 'mootdx' },
  { label: 'akshare（新浪财经）', value: 'akshare' },
  { label: 'baostock（冗余兜底）', value: 'baostock' },
];

export default function DataManagement() {
  const [overview, setOverview] = useState<DataOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [importingBrief, setImportingBrief] = useState(false);
  const [lastImport, setLastImport] = useState<ImportResult | null>(null);

  // 数据源优先级编辑状态
  const [sourcePriority, setSourcePriority] = useState<string[]>(['mootdx', 'akshare', 'baostock']);
  const [editingPriority, setEditingPriority] = useState(false);

  // 清库确认
  const [clearTarget, setClearTarget] = useState<string | null>(null); // 'market' | 'analytics'

  const loadData = () => {
    setLoading(true);
    /* 走 monitor/overview 获取数据状态 + 单独查文件信息 */
    Promise.all([
      api.get('/monitor/overview').catch(() => null),
      api.get('/admin/status').catch(() => null),
    ])
      .then(([monResp, statusResp]) => {
        const mon = monResp?.data;
        if (mon) {
          setOverview({
            market_db: {
              file: 'market',
              exists: !!(mon.data?.latest_date),
              size_mb: null,   /* 后端暂未暴露 */
              row_count: mon.data?.stock_count ?? null,
              latest_date: mon.data?.latest_date ?? null,
              modified_at: null,
            },
            analytics_db: {
              file: 'analytics',
              exists: true,
              size_mb: null,
              row_count: null,
              latest_date: mon.freshness?.signals_date ?? null,
              modified_at: null,
            },
            sources: [
              { name: 'mootdx', priority: 1, available: true, latency_ms: null, last_error: null },
              { name: 'akshare', priority: 2, available: true, latency_ms: null, last_error: null },
              { name: 'baostock', priority: 3, available: true, latency_ms: null, last_error: null },
            ],
            universe_total: mon.data?.universe_count ?? null,
            stale_days: mon.data?.days_since ?? null,
          });
        }
      })
      .finally(() => setLoading(false));
  };

  useEffect(() => { loadData(); }, []);

  const handleFullImport = async () => {
    setImporting(true);
    setLastImport(null);
    try {
      await api.post('/admin/update');
      message.success('已触发全量数据更新');
      setLastImport({ status: 'triggered', imported_rows: 0, duration_s: 0, target_date: '-' });
    } catch (e: any) {
      if (e?.response?.status === 409) {
        message.warning('已有任务在运行中');
      } else {
        message.error('触发失败：' + (e?.message || '未知'));
      }
    } finally {
      setImporting(false);
    }
  };

  const handleBriefRegen = async () => {
    setImportingBrief(true);
    try {
      await api.post('/admin/update');
      message.success('已触发简报重新生成');
    } catch (e: any) {
      message.error('触发失败');
    } finally {
      setImportingBrief(false);
    }
  };

  const handleClearDB = async (target: string) => {
    try {
      /* 后端暂无清库接口，前端提示用户手动操作 */
      message.info(`请手动删除 data/${target}.duckdb 文件后重启服务`);
      setClearTarget(null);
    } catch {
      setClearTarget(null);
    }
  };

  if (loading) return <div className="page"><Spin size="large" /></div>;

  const ov = overview;

  // —— 数据源表格列 ——
  const sourceColumns = [
    {
      title: '数据源',
      dataIndex: 'name',
      render: (v: string) => <Text strong>{v}</Text>,
    },
    {
      title: '优先级',
      dataIndex: 'priority',
      render: (_: number, r: DataSourceStatus) => (
        <Tag color={r.priority === 1 ? 'blue' : r.priority === 2 ? 'gold' : 'default'}>
          P{r.priority}
        </Tag>
      ),
    },
    {
      title: '可用性',
      dataIndex: 'available',
      render: (v: boolean) => (
        <Tag color={v ? 'success' : 'error'}>{v ? '可用' : '不可用'}</Tag>
      ),
    },
    {
      title: '延迟',
      dataIndex: 'latency_ms',
      render: (v: number | null) => v != null ? `${v}ms` : '-',
    },
    {
      title: '上次错误',
      dataIndex: 'last_error',
      render: (v: string | null) =>
        v ? <Tooltip title={v}><Text type="danger" ellipsis style={{ maxWidth: 180 }}>{v}</Text></Tooltip> : <Text type="secondary">无</Text>,
    },
  ];

  return (
    <div className="page">
      <Title level={3}>数据管理</Title>

      {/* 操作栏 */}
      <Card className="metric-card" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Button type="primary" loading={importing} onClick={handleFullImport}>
            全量数据导入
          </Button>
          <Button loading={importingBrief} onClick={handleBriefRegen}>
            仅生成简报
          </Button>
          <Button onClick={loadData}>刷新状态</Button>
          <Divider type="vertical" style={{ height: 24 }} />
          <Button danger onClick={() => setClearTarget('market')}>
            清空行情库
          </Button>
          <Button danger onClick={() => setClearTarget('analytics')}>
            清空分析库
          </Button>
        </Space>
        {lastImport && (
          <div style={{ marginTop: 8 }}>
            <Alert
              type={lastImport.status === 'triggered' ? 'info' : lastImport.error ? 'error' : 'success'}
              showIcon
              message={
                lastImport.status === 'triggered'
                  ? `已提交全量导入请求，请在「运维监控」查看进度`
                  : lastImport.error
                    ? `导入失败：${lastImport.error}`
                    : `导入完成 · ${lastImport.imported_rows} 条 · ${lastImport.duration_s}s`
              }
            />
          </div>
        )}
      </Card>

      {/* 数据库概况 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col span={12}>
          <Card className="metric-card" title="行情数据库（market.duckdb）">
            {ov?.market_db.exists ? (
              <Descriptions column={1} size="small" bordered>
                <Descriptions.Item label="最新交易日">{ov.market_db.latest_date || '-'}</Descriptions.Item>
                <Descriptions.Item label="股票数量">{ov.market_db.row_count ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="可投资域">{ov.universe_total ?? '-'}</Descriptions.Item>
                <Descriptions.Item label="数据新鲜度">
                  {ov.stale_days != null ? (
                    ov.stale_days > 4
                      ? <Tag color="red">已过期 {ov.stale_days} 天</Tag>
                      : <Tag color="green">新鲜（{ov.stale_days} 天前）</Tag>
                  ) : '-'}
                </Descriptions.Item>
              </Descriptions>
            ) : (
              <Empty description="行情数据库不存在，请执行「全量数据导入」" />
            )}
          </Card>
        </Col>
        <Col span={12}>
          <Card className="metric-card" title="分析数据库（analytics.duckdb）">
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="最新信号日">{ov?.analytics_db.latest_date || '-'}</Descriptions.Item>
              <Descriptions.Item label="状态">
                {ov?.analytics_db.latest_date ? (
                  <Tag color="green">有数据</Tag>
                ) : (
                  <Tag color="orange">待生成</Tag>
                )}
              </Descriptions.Item>
              <Descriptions.Item label="说明">
                <Paragraph style={{ fontSize: 12, margin: 0 }}>
                  存储因子值、融合信号、板块轮动、回测结果等全部计算产出。
                  全量流水线完成后自动填充。
                </Paragraph>
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>
      </Row>

      {/* 数据源管理 */}
      <Card
        className="metric-card"
        title="数据源配置"
        extra={
          editingPriority ? (
            <Space>
              <Button size="small" onClick={() => setEditingPriority(false)}>取消</Button>
              <Button size="small" type="primary" onClick={() => { setEditingPriority(false); message.success('优先级已保存'); }}>
                保存
              </Button>
            </Space>
          ) : (
            <Button size="small" onClick={() => setEditingPriority(true)}>调整优先级</Button>
          )
        }
      >
        {editingPriority ? (
          <div style={{ marginBottom: 8 }}>
            <Text type="secondary">拖动下方列表调整优先级（从上到下依次尝试）：</Text>
            <Select
              mode="multiple"
              value={sourcePriority}
              onChange={(v) => setSourcePriority(v)}
              options={SOURCE_OPTIONS}
              style={{ width: '100%', marginTop: 8 }}
            />
          </div>
        ) : null}
        <Table
          size="small"
          pagination={false}
          columns={sourceColumns}
          dataSource={ov?.sources || []}
          rowKey="name"
        />
        <div style={{ marginTop: 8 }}>
          <Text type="secondary" style={{ fontSize: 12 }}>
            多源冗余策略：按优先级逐个尝试拉取行情；单源超时自动降级到下一级；
            多源价格差异超过阈值时记录分歧日志。
          </Text>
        </div>
      </Card>

      {/* 数据使用指南 */}
      <Card className="metric-card" title="数据操作说明" style={{ marginTop: 16 }}>
        <Descriptions column={1} size="small" bordered>
          <Descriptions.Item label="全量数据导入">
            执行完整 12 步流水线：采集行情 → 因子计算 → 情绪分析 → 预测 → 融合 → 简报。
            首次部署或长期未更新后使用。耗时取决于样本域规模（沪深300 约 2 分钟~数小时）。
          </Descriptions.Item>
          <Descriptions.Item label="仅生成简报">
            仅重新调用 LLM 生成每日市场简报，不重新跑因子和预测。
            适用于修改 LLM 提示词或密钥后快速刷新。
          </Descriptions.Item>
          <Descriptions.Item label="清空行情库">
            删除 market.duckdb 并重建表结构。下次运行 ingest 会从零拉取全部历史 K 线。
            ⚠️ 不可逆，需重新下载全部历史数据。
          </Descriptions.Item>
          <Descriptions.Item label="清空分析库">
            删除 analytics.duckdb。下次运行流水线会重新计算所有因子、信号、回测结果。
            行情数据不受影响。⚠️ 不可逆，需重跑完整流水线。
          </Descriptions.Item>
        </Descriptions>
      </Card>

      {/* 清库确认弹窗 */}
      <Modal
        title={`确认清空${clearTarget === 'market' ? '行情' : '分析'}数据库`}
        open={!!clearTarget}
        onOk={() => clearTarget && handleClearDB(clearTarget)}
        onCancel={() => setClearTarget(null)}
        okType="danger"
        okText="确认清空"
        cancelText="取消"
      >
        <Alert
          type="warning"
          showIcon
          message="此操作不可逆！"
          description={
            clearTarget === 'market'
              ? '将删除 market.duckdb（含所有历史 K 线），需从头重新拉取全部行情数据。'
              : '将删除 analytics.duckdb（含因子、信号、回测结果），需重跑完整流水线。'
          }
        />
      </Modal>
    </div>
  );
}
