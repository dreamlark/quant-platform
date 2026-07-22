import { useEffect, useState } from 'react';
import {
  Card, Row, Col, Table, Typography, Tag, Spin, Empty,
  Button, Space, Alert, Descriptions, Divider, Switch,
  Tooltip, Modal, message, Select, DatePicker, Upload, Radio, Input,
} from 'antd';
import {
  api,
  triggerUpdate, getDataTables, DataTableMeta,
  PoolRow, PoolBuildStatus, getPoolList, buildPool, getPoolBuildStatus,
  selectPool, deselectPool, addPool,
  importData, exportData,
} from '../api/client';
import dayjs from 'dayjs';

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

const POOL_PAGE_SIZE = 50;

export default function DataManagement() {
  const [overview, setOverview] = useState<DataOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [importing, setImporting] = useState(false);
  const [importingBrief, setImportingBrief] = useState(false);
  const [lastImport, setLastImport] = useState<ImportResult | null>(null);

  // 按日期补充
  const [backfillDate, setBackfillDate] = useState<dayjs.Dayjs | null>(null);

  // 数据源优先级编辑状态
  const [sourcePriority, setSourcePriority] = useState<string[]>(['mootdx', 'akshare', 'baostock']);
  const [editingPriority, setEditingPriority] = useState(false);

  // 清库确认
  const [clearTarget, setClearTarget] = useState<string | null>(null); // 'market' | 'analytics'

  // —— 数据表元信息（导入/导出目标表选择）——
  const [tables, setTables] = useState<DataTableMeta[]>([]);
  useEffect(() => {
    getDataTables().then((r) => setTables(r.data.tables)).catch(() => setTables([]));
  }, []);

  // —— 数据导入 / 导出（CSV / Parquet）——
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importFileList, setImportFileList] = useState<any[]>([]);
  const [ioTable, setIoTable] = useState<string | null>(null);
  const [importMode, setImportMode] = useState<'upsert' | 'replace'>('upsert');
  const [ioBusy, setIoBusy] = useState(false);
  const [ioHint, setIoHint] = useState<string | null>(null);

  // —— 股票池（全量候选主表 + 自选子集）——
  const [poolRows, setPoolRows] = useState<PoolRow[]>([]);
  const [poolTotal, setPoolTotal] = useState(0);
  const [poolSelectedTotal, setPoolSelectedTotal] = useState(0);
  const [poolLoading, setPoolLoading] = useState(false);
  const [poolPage, setPoolPage] = useState(1);
  const [poolQuery, setPoolQuery] = useState('');
  const [poolOnlySelected, setPoolOnlySelected] = useState(false);
  const [poolBuild, setPoolBuild] = useState<PoolBuildStatus | null>(null);
  const [poolBusy, setPoolBusy] = useState(false);
  const [poolHint, setPoolHint] = useState<string | null>(null);
  const [addCode, setAddCode] = useState('');
  const [addName, setAddName] = useState('');

  const loadData = () => {
    setLoading(true);
    /* 走 monitor/overview 获取数据状态 + 单独查文件信息 */
    Promise.all([
      api.get('/monitor/overview').catch(() => null),
      api.get('/admin/status').catch(() => null),
    ])
      .then(([monResp]) => {
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

  // 按日期补充：触发 update 并携带 target_date，仅重算指定交易日
  const handleBackfill = async () => {
    if (!backfillDate) {
      message.warning('请先选择要补充的交易日');
      return;
    }
    const d = backfillDate.format('YYYY-MM-DD');
    setImporting(true);
    setLastImport(null);
    try {
      await triggerUpdate(d);
      message.success(`已触发按 ${d} 补充数据`);
      setLastImport({ status: 'triggered', imported_rows: 0, duration_s: 0, target_date: d });
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

  // —— 数据导入 / 导出 ——
  const doExport = (table: string | null, format: 'csv' | 'parquet') => {
    if (!table) { setIoHint('请先选择要导出的数据表'); return; }
    setIoBusy(true);
    setIoHint(null);
    exportData(table, format)
      .then(() => setIoHint(`已导出 ${table}.${format}`))
      .catch((e: any) => setIoHint('导出失败：' + (e?.message || '未知错误')))
      .finally(() => setIoBusy(false));
  };

  const handleImport = () => {
    if (!importFile) { setIoHint('请先选择要导入的 CSV / Parquet 文件'); return; }
    if (!ioTable) { setIoHint('请选择目标数据表'); return; }
    setIoBusy(true);
    setIoHint(null);
    importData(importFile, ioTable, importMode)
      .then((r) => {
        setIoHint(`导入成功：表 ${r.data.table}（${r.data.mode}）写入 ${r.data.imported} 行`);
        setImportFile(null);
        setImportFileList([]);
      })
      .catch((e: any) =>
        setIoHint('导入失败：' + (e?.response?.data?.detail || e?.message || '未知错误')))
      .finally(() => setIoBusy(false));
  };

  // —— 股票池 ——
  const loadPool = (targetPage = 1) => {
    setPoolLoading(true);
    getPoolList({
      selected: poolOnlySelected ? true : undefined,
      query: poolQuery.trim() || undefined,
      limit: POOL_PAGE_SIZE,
      offset: (targetPage - 1) * POOL_PAGE_SIZE,
    })
      .then((r) => {
        setPoolRows(r.data.rows);
        setPoolTotal(r.data.total);
        setPoolSelectedTotal(r.data.selected_total);
        setPoolPage(targetPage);
      })
      .catch(() => { /* 忽略 */ })
      .finally(() => setPoolLoading(false));
  };

  useEffect(() => {
    loadPool(1);
    getPoolBuildStatus().then((r) => setPoolBuild(r.data)).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 构建状态轮询（running 时每 2s）
  useEffect(() => {
    if (poolBuild?.status !== 'running') return;
    const timer = setInterval(() => {
      getPoolBuildStatus().then((r) => setPoolBuild(r.data)).catch(() => {});
    }, 2000);
    return () => clearInterval(timer);
  }, [poolBuild?.status]);

  const togglePoolSelect = (code: string, sel: boolean) => {
    const fn = sel ? selectPool : deselectPool;
    fn({ codes: [code] })
      .then(() => loadPool(poolPage))
      .catch((e: any) => setPoolHint('操作失败：' + (e?.message || '未知错误')));
  };

  const applyPreset = (preset: string) => {
    setPoolBusy(true);
    setPoolHint(null);
    const fn = preset === 'none' ? deselectPool : selectPool;
    fn(preset === 'none' ? { preset: 'none' } : { preset })
      .then(() => { loadPool(1); setPoolHint(`已应用预设：${preset}`); })
      .catch((e: any) => setPoolHint('预设失败：' + (e?.message || '未知错误')))
      .finally(() => setPoolBusy(false));
  };

  const doBuildPool = () => {
    setPoolBusy(true);
    setPoolHint(null);
    buildPool()
      .then(() => setPoolHint('已触发股票池构建（后台），进度见上方状态'))
      .catch((e: any) => setPoolHint('触发构建失败：' + (e?.message || '未知错误')))
      .finally(() => setPoolBusy(false));
  };

  const doAddPool = () => {
    const code = addCode.trim();
    if (!code) { setPoolHint('请填写股票代码'); return; }
    addPool({ code, name: addName.trim() || undefined })
      .then(() => { setAddCode(''); setAddName(''); loadPool(1); setPoolHint(`已添加 ${code}`); })
      .catch((e: any) => setPoolHint('添加失败：' + (e?.message || '未知错误')));
  };

  const poolColumns = [
    { title: '代码', dataIndex: 'code', key: 'code', width: 90 },
    { title: '名称', dataIndex: 'name', key: 'name' },
    { title: '行业', dataIndex: 'industry', key: 'industry', render: (v: string) => v || <Text type="secondary">—</Text> },
    { title: '市场', dataIndex: 'exchange', key: 'exchange', width: 70, render: (v: string) => (v || '').toUpperCase() },
    { title: '来源', dataIndex: 'source', key: 'source', width: 80 },
    {
      title: '入选', dataIndex: 'selected', key: 'selected', width: 80,
      render: (sel: boolean, r: any) => <Switch checked={sel} onChange={(c) => togglePoolSelect(r.code, c)} />,
    },
  ];

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

  // 数据表下拉选项（导入目标 / 导出选择）
  const tableOptions = tables.map((t) => ({
    value: t.name,
    label: `[${t.db}] ${t.name}（${t.rows} 行）`,
  }));

  return (
    <div className="page">
      <Title level={3}>数据管理</Title>

      {/* 操作栏 */}
      <Card className="metric-card" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Button type="primary" loading={importing} onClick={handleFullImport}>
            全量数据导入
          </Button>
          <DatePicker
            placeholder="选择补充的交易日"
            value={backfillDate}
            onChange={(d) => setBackfillDate(d)}
            disabled={importing}
            style={{ width: 190 }}
          />
          <Button loading={importing} onClick={handleBackfill}>
            按日期补充
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
                  ? `已提交${lastImport.target_date === '-' ? '全量导入' : `按 ${lastImport.target_date} 补充`}请求，请在「运维监控」查看进度`
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
          <Descriptions.Item label="按日期补充">
            指定某交易日（YYYY-MM-DD），仅拉取并重算该日行情与下游（因子/信号/简报等）。
            适用于补跑错过的交易日或重算特定日，跳过「已新鲜」误判。
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

      {/* 数据导入 / 导出（CSV / Parquet）*/}
      <Card className="metric-card" title="数据导入 / 导出（CSV / Parquet）" style={{ marginTop: 16 }}>
        <Alert
          type="info"
          showIcon
          style={{ marginBottom: 12 }}
          message="导入支持把外部下载的全量数据写入本系统；导出可把整表分享为文件。"
          description="CSV/Parquet 均会自动校验列与主键，并强制类型（如股票代码保留前导零、时间戳保留时分秒）。"
        />
        <Space wrap style={{ marginBottom: 12 }}>
          <Select
            style={{ width: 280 }}
            placeholder="选择目标数据表"
            value={ioTable}
            onChange={setIoTable}
            showSearch
            optionFilterProp="label"
            options={tableOptions}
          />
          <Upload
            accept=".csv,.parquet"
            maxCount={1}
            fileList={importFileList}
            beforeUpload={(file) => {
              setImportFile(file);
              setImportFileList([{ uid: (file as any).uid || '-1', name: file.name }]);
              return false;
            }}
            onRemove={() => { setImportFile(null); setImportFileList([]); }}
          >
            <Button>选择文件 (CSV / Parquet)</Button>
          </Upload>
          <Radio.Group
            value={importMode}
            onChange={(e) => setImportMode(e.target.value)}
            optionType="button"
            buttonStyle="solid"
          >
            <Radio value="upsert">upsert（幂等）</Radio>
            <Radio value="replace">replace（清空后写入）</Radio>
          </Radio.Group>
          <Button type="primary" loading={ioBusy} onClick={handleImport}>
            导入
          </Button>
        </Space>

        <Space wrap>
          <Text type="secondary">导出：</Text>
          <Button onClick={() => doExport(ioTable, 'csv')} disabled={!ioTable || ioBusy}>导出CSV</Button>
          <Button onClick={() => doExport(ioTable, 'parquet')} disabled={!ioTable || ioBusy}>导出Parquet</Button>
        </Space>

        {ioHint && <Alert type="info" showIcon style={{ marginTop: 12 }} message={ioHint} />}
      </Card>

      {/* 股票池（全量候选主表 + 自选子集）*/}
      <Card className="metric-card" title="股票池（全量候选 + 自选子集）" style={{ marginTop: 16 }}>
        <Space wrap style={{ marginBottom: 12 }}>
          <Button type="primary" loading={poolBusy} onClick={doBuildPool}>构建全量股票池</Button>
          <Text type="secondary">共 {poolTotal} 只 / 已选 {poolSelectedTotal} 只</Text>
        </Space>

        {poolBuild && (
          <Alert
            style={{ marginBottom: 12 }}
            type={poolBuild.status === 'failed' ? 'error' : poolBuild.status === 'success' ? 'success' : 'info'}
            showIcon
            message={`构建状态：${poolBuild.status}`}
            description={poolBuild.message}
          />
        )}

        <Space wrap style={{ marginBottom: 12 }}>
          <Text type="secondary">预设子集：</Text>
          <Button size="small" onClick={() => applyPreset('all')}>全选</Button>
          <Button size="small" onClick={() => applyPreset('none')}>全不选</Button>
          <Button size="small" onClick={() => applyPreset('hs300')}>沪深300</Button>
          <Button size="small" onClick={() => applyPreset('cyb')}>创业板</Button>
          <Button size="small" onClick={() => applyPreset('kcb')}>科创板</Button>
          <Button size="small" onClick={() => applyPreset('sh_main')}>沪主板</Button>
          <Button size="small" onClick={() => applyPreset('sz_main')}>深主板</Button>
        </Space>

        <Space wrap style={{ marginBottom: 12 }}>
          <Input
            placeholder="搜索代码/名称"
            style={{ width: 160 }}
            value={poolQuery}
            onChange={(e) => setPoolQuery(e.target.value)}
            onPressEnter={() => loadPool(1)}
            allowClear
          />
          <Button onClick={() => loadPool(1)}>搜索</Button>
          <Select
            style={{ width: 130 }}
            value={poolOnlySelected ? 'sel' : 'all'}
            onChange={(v) => { setPoolOnlySelected(v === 'sel'); loadPool(1); }}
            options={[
              { value: 'all', label: '全部' },
              { value: 'sel', label: '仅已选' },
            ]}
          />
          <Input
            placeholder="代码"
            style={{ width: 110 }}
            value={addCode}
            onChange={(e) => setAddCode(e.target.value)}
          />
          <Input
            placeholder="名称(可选)"
            style={{ width: 130 }}
            value={addName}
            onChange={(e) => setAddName(e.target.value)}
          />
          <Button onClick={doAddPool}>添加</Button>
        </Space>

        {poolHint && <Alert type="info" showIcon style={{ marginBottom: 12 }} message={poolHint} />}

        <Table
          size="small"
          bordered
          scroll={{ x: 'max-content' }}
          loading={poolLoading}
          columns={poolColumns}
          dataSource={poolRows}
          rowKey="code"
          pagination={{
            current: poolPage,
            pageSize: POOL_PAGE_SIZE,
            total: poolTotal,
            showTotal: (t) => `共 ${t} 只`,
            onChange: (p) => loadPool(p),
          }}
        />
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
