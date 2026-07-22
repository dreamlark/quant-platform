import { useEffect, useState, useCallback } from 'react';
import {
  Card, Form, Input, Button, Select, InputNumber, Switch, Divider,
  Typography, message, Spin, Tabs, Space, Tag, Modal, Table, Alert,
  Row, Col,
} from 'antd';
import {
  SettingOutlined, KeyOutlined, DatabaseOutlined, ClockCircleOutlined,
  FireOutlined, BgColorsOutlined, ApiOutlined, FolderOpenOutlined,
  CheckCircleOutlined, ExclamationCircleOutlined,
} from '@ant-design/icons';
import {
  getSettings, updateSettings, testLLM, getPathsInfo, migratePaths,
  type SettingsView, type PathInfo,
} from '../api/client';

const { Title, Text } = Typography;
const { Option } = Select;

const THEME_OPTIONS = [
  { value: 'dark', label: '暗色经典', desc: '默认暗色主题' },
  { value: 'light', label: '亮色模式', desc: '白天明亮风格' },
  { value: 'compact', label: '紧凑暗色', desc: '小字体紧凑布局' },
  { value: 'techblue', label: '科技蓝', desc: '深蓝底霓虹蓝强调色' },
];

const CHART_COLOR_OPTIONS = [
  { value: 'red_up', label: '红涨绿跌（A股惯例）' },
  { value: 'green_up', label: '绿涨红跌（国际惯例）' },
];

const LANGUAGE_OPTIONS = [
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'English' },
];

const LLM_PROVIDERS = [
  { value: 'deepseek', label: 'DeepSeek', defaultUrl: 'https://api.deepseek.com', defaultModel: 'deepseek-chat' },
  { value: 'openai', label: 'OpenAI', defaultUrl: 'https://api.openai.com/v1', defaultModel: 'gpt-4o-mini' },
  { value: 'custom', label: '自定义 (OpenAI 兼容)', defaultUrl: '', defaultModel: '' },
];

export default function Settings() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [settings, setSettings] = useState<SettingsView | null>(null);
  const [pathsInfo, setPathsInfo] = useState<Record<string, PathInfo>>({});
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);
  const [migrateModalOpen, setMigrateModalOpen] = useState(false);
  const [newDataDir, setNewDataDir] = useState('');

  // 本地表单状态
  const [llmForm, setLlmForm] = useState({
    provider: 'deepseek',
    model: '',
    base_url: '',
    api_key: '',
    temperature: 0.3,
    max_tokens: 2048,
    cache_enabled: true,
  });
  const [pathForm, setPathForm] = useState({
    data_dir: '',
    market_db: '',
    analytics_db: '',
    raw_cache: '',
  });
  const [schedulerForm, setSchedulerForm] = useState({
    enabled: false,
    cron: '30 18 * * 1-5',
    timezone: 'Asia/Shanghai',
  });
  const [hotspotForm, setHotspotForm] = useState({
    enabled: false,
    batch_size: 8,
    daemon_interval: 300,
    simhash_threshold: 3,
  });
  const [fusionForm, setFusionForm] = useState({
    hotspot_alpha: 0.3,
    regime_adjust_enabled: true,
  });
  const [uiForm, setUiForm] = useState({
    theme: 'dark',
    chart_up_color: 'red_up',
    language: 'zh',
  });

  const fetchAll = useCallback(async () => {
    setLoading(true);
    try {
      const [settingsRes, pathsRes] = await Promise.all([
        getSettings(),
        getPathsInfo(),
      ]);
      const s = settingsRes.data;
      setSettings(s);
      setLlmForm({
        provider: s.llm.provider,
        model: s.llm.model,
        base_url: s.llm.base_url,
        api_key: '',
        temperature: s.llm.temperature,
        max_tokens: s.llm.max_tokens,
        cache_enabled: s.llm.cache_enabled,
      });
      setPathForm(s.paths);
      setSchedulerForm(s.scheduler);
      setHotspotForm(s.hotspot);
      setFusionForm(s.fusion);
      setUiForm({
        theme: s.ui?.theme || 'dark',
        chart_up_color: s.ui?.chart_up_color || 'red_up',
        language: s.ui?.language || 'zh',
      });
      setPathsInfo(pathsRes.data);
    } catch (err: any) {
      message.error('加载设置失败');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAll();
  }, [fetchAll]);

  // ---- 保存各段 ----
  const saveLLM = async () => {
    setSaving(true);
    try {
      await updateSettings({
        llm: {
          provider: llmForm.provider,
          model: llmForm.model,
          base_url: llmForm.base_url,
          api_key: llmForm.api_key || undefined,
          temperature: llmForm.temperature,
          max_tokens: llmForm.max_tokens,
          cache_enabled: llmForm.cache_enabled,
        },
      });
      message.success('LLM 设置已保存');
      if (llmForm.api_key) {
        setLlmForm((f) => ({ ...f, api_key: '' }));
      }
      fetchAll();
    } catch (err: any) {
      message.error('保存失败：' + (err.response?.data?.detail || err.message));
    } finally {
      setSaving(false);
    }
  };

  const savePaths = async () => {
    setSaving(true);
    try {
      await updateSettings({ paths: pathForm });
      message.success('路径设置已保存（重启 API 后生效）');
      fetchAll();
    } catch (err: any) {
      message.error('保存失败：' + (err.response?.data?.detail || err.message));
    } finally {
      setSaving(false);
    }
  };

  const saveScheduler = async () => {
    setSaving(true);
    try {
      await updateSettings({ scheduler: schedulerForm });
      message.success('调度设置已保存');
    } catch (err: any) {
      message.error('保存失败：' + (err.response?.data?.detail || err.message));
    } finally {
      setSaving(false);
    }
  };

  const saveHotspot = async () => {
    setSaving(true);
    try {
      await updateSettings({ hotspot: hotspotForm });
      message.success('热点设置已保存');
    } catch (err: any) {
      message.error('保存失败：' + (err.response?.data?.detail || err.message));
    } finally {
      setSaving(false);
    }
  };

  const saveFusion = async () => {
    setSaving(true);
    try {
      await updateSettings({ fusion: fusionForm });
      message.success('融合参数已保存');
    } catch (err: any) {
      message.error('保存失败：' + (err.response?.data?.detail || err.message));
    } finally {
      setSaving(false);
    }
  };

  const saveUI = async () => {
    setSaving(true);
    try {
      await updateSettings({ ui: uiForm });
      message.success('界面偏好已保存，刷新页面生效');
      // 触发主题变更事件
      window.dispatchEvent(new CustomEvent('theme-change', { detail: uiForm.theme }));
    } catch (err: any) {
      message.error('保存失败：' + (err.response?.data?.detail || err.message));
    } finally {
      setSaving(false);
    }
  };

  // ---- 测试 LLM 连接 ----
  const handleTestLLM = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      // 如果有新 key 先保存
      if (llmForm.api_key) {
        await updateSettings({
          llm: {
            provider: llmForm.provider,
            model: llmForm.model,
            base_url: llmForm.base_url,
            api_key: llmForm.api_key,
            temperature: llmForm.temperature,
            max_tokens: llmForm.max_tokens,
            cache_enabled: llmForm.cache_enabled,
          },
        });
      }
      const res = await testLLM();
      setTestResult({ success: res.data.success, message: res.data.message });
      if (res.data.success) {
        message.success('LLM 连接成功');
      } else {
        message.warning('LLM 连接失败');
      }
    } catch (err: any) {
      setTestResult({ success: false, message: err.message });
      message.error('测试失败');
    } finally {
      setTesting(false);
    }
  };

  // ---- 路径迁移 ----
  const handleMigrate = async () => {
    if (!newDataDir) {
      message.warning('请输入新数据目录路径');
      return;
    }
    try {
      const res = await migratePaths(newDataDir);
      message.success(res.data.message);
      setMigrateModalOpen(false);
      setNewDataDir('');
      fetchAll();
    } catch (err: any) {
      message.error('迁移失败：' + (err.response?.data?.detail || err.message));
    }
  };

  // ---- Provider 切换时填充默认值 ----
  const handleProviderChange = (provider: string) => {
    const p = LLM_PROVIDERS.find((x) => x.value === provider);
    if (p) {
      setLlmForm((f) => ({
        ...f,
        provider,
        base_url: f.base_url || p.defaultUrl,
        model: f.model || p.defaultModel,
      }));
    }
  };

  if (loading) {
    return (
      <div style={{ padding: 48, textAlign: 'center' }}>
        <Spin size="large" />
      </div>
    );
  }

  // ---- 路径信息表格列 ----
  const pathColumns = [
    { title: '配置项', dataIndex: 'key', key: 'key', render: (k: string) => <Tag>{k}</Tag> },
    { title: '配置路径', dataIndex: 'configured', key: 'configured' },
    { title: '绝对路径', dataIndex: 'absolute', key: 'absolute', ellipsis: true },
    {
      title: '状态', dataIndex: 'exists', key: 'exists', width: 80,
      render: (exists: boolean) => exists
        ? <CheckCircleOutlined style={{ color: '#52c41a' }} />
        : <ExclamationCircleOutlined style={{ color: '#faad14' }} />,
    },
    {
      title: '大小', dataIndex: 'size_mb', key: 'size_mb', width: 100,
      render: (v: number | null | undefined) => v != null ? `${v} MB` : '-',
    },
  ];
  const pathData = Object.entries(pathsInfo).map(([k, v]) => ({ ...v, key: k }));

  return (
    <div style={{ padding: 24, maxWidth: 900 }}>
      <Title level={3}>
        <SettingOutlined /> 系统设置
      </Title>

      <Tabs
        defaultActiveKey="llm"
        items={[
          {
            key: 'llm',
            label: <span><KeyOutlined /> 大模型配置</span>,
            children: (
              <Card size="small">
                <Form layout="vertical" style={{ maxWidth: 600 }}>
                  <Form.Item label="服务商">
                    <Select
                      value={llmForm.provider}
                      onChange={handleProviderChange}
                      style={{ width: '100%' }}
                    >
                      {LLM_PROVIDERS.map((p) => (
                        <Option key={p.value} value={p.value}>{p.label}</Option>
                      ))}
                    </Select>
                  </Form.Item>
                  <Form.Item label="模型名称">
                    <Input
                      value={llmForm.model}
                      onChange={(e) => setLlmForm({ ...llmForm, model: e.target.value })}
                      placeholder="deepseek-chat / gpt-4o-mini"
                    />
                  </Form.Item>
                  <Form.Item label="API Base URL">
                    <Input
                      value={llmForm.base_url}
                      onChange={(e) => setLlmForm({ ...llmForm, base_url: e.target.value })}
                      placeholder="https://api.deepseek.com"
                    />
                  </Form.Item>
                  <Form.Item
                    label={
                      <Space>
                        <span>API Key</span>
                        {settings?.llm.is_configured && (
                          <Tag color="green">已配置 ({settings?.llm.api_key_masked})</Tag>
                        )}
                        {!settings?.llm.is_configured && (
                          <Tag color="orange">未配置</Tag>
                        )}
                      </Space>
                    }
                  >
                    <Input.Password
                      value={llmForm.api_key}
                      onChange={(e) => setLlmForm({ ...llmForm, api_key: e.target.value })}
                      placeholder={settings?.llm.is_configured ? '已配置（输入新值覆盖）' : '输入 API Key'}
                      autoComplete="new-password"
                    />
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      环境变量名：{settings?.llm.api_key_env}。Key 保存在环境变量中，不落盘配置文件。
                    </Text>
                  </Form.Item>
                  <Row gutter={16}>
                    <Col span={12}>
                      <Form.Item label="Temperature">
                        <InputNumber
                          value={llmForm.temperature}
                          onChange={(v) => setLlmForm({ ...llmForm, temperature: v ?? 0.3 })}
                          min={0} max={2} step={0.1}
                          style={{ width: '100%' }}
                        />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item label="Max Tokens">
                        <InputNumber
                          value={llmForm.max_tokens}
                          onChange={(v) => setLlmForm({ ...llmForm, max_tokens: v ?? 2048 })}
                          min={100} max={32768} step={256}
                          style={{ width: '100%' }}
                        />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Form.Item label="缓存">
                    <Switch
                      checked={llmForm.cache_enabled}
                      onChange={(v) => setLlmForm({ ...llmForm, cache_enabled: v })}
                    />
                    <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                      启用 MD5 缓存减少 API 调用
                    </Text>
                  </Form.Item>

                  {testResult && (
                    <Alert
                      type={testResult.success ? 'success' : 'error'}
                      message={testResult.message}
                      showIcon
                      closable
                      onClose={() => setTestResult(null)}
                      style={{ marginBottom: 16 }}
                    />
                  )}

                  <Space>
                    <Button
                      type="primary"
                      icon={<CheckCircleOutlined />}
                      onClick={saveLLM}
                      loading={saving}
                    >
                      保存
                    </Button>
                    <Button
                      icon={<ApiOutlined />}
                      onClick={handleTestLLM}
                      loading={testing}
                    >
                      测试连接
                    </Button>
                  </Space>
                </Form>
              </Card>
            ),
          },
          {
            key: 'ui',
            label: <span><BgColorsOutlined /> 界面偏好</span>,
            children: (
              <Card size="small">
                <Form layout="vertical" style={{ maxWidth: 500 }}>
                  <Form.Item label="主题模式">
                    <Select
                      value={uiForm.theme}
                      onChange={(v) => setUiForm({ ...uiForm, theme: v })}
                      style={{ width: '100%' }}
                    >
                      {THEME_OPTIONS.map((t) => (
                        <Option key={t.value} value={t.value}>
                          <Space>
                            <span>{t.label}</span>
                            <Text type="secondary" style={{ fontSize: 12 }}>{t.desc}</Text>
                          </Space>
                        </Option>
                      ))}
                    </Select>
                  </Form.Item>
                  <Form.Item label="图表涨跌颜色">
                    <Select
                      value={uiForm.chart_up_color}
                      onChange={(v) => setUiForm({ ...uiForm, chart_up_color: v })}
                      style={{ width: '100%' }}
                    >
                      {CHART_COLOR_OPTIONS.map((c) => (
                        <Option key={c.value} value={c.value}>{c.label}</Option>
                      ))}
                    </Select>
                  </Form.Item>
                  <Form.Item label="语言">
                    <Select
                      value={uiForm.language}
                      onChange={(v) => setUiForm({ ...uiForm, language: v })}
                      style={{ width: '100%' }}
                    >
                      {LANGUAGE_OPTIONS.map((l) => (
                        <Option key={l.value} value={l.value}>{l.label}</Option>
                      ))}
                    </Select>
                  </Form.Item>
                  <Button
                    type="primary"
                    icon={<CheckCircleOutlined />}
                    onClick={saveUI}
                    loading={saving}
                  >
                    保存并应用
                  </Button>
                </Form>
              </Card>
            ),
          },
          {
            key: 'paths',
            label: <span><DatabaseOutlined /> 数据存储</span>,
            children: (
              <Card size="small">
                <Form layout="vertical" style={{ maxWidth: 600 }}>
                  <Form.Item label="数据目录">
                    <Input
                      value={pathForm.data_dir}
                      onChange={(e) => setPathForm({ ...pathForm, data_dir: e.target.value })}
                    />
                  </Form.Item>
                  <Form.Item label="行情库 (DuckDB)">
                    <Input
                      value={pathForm.market_db}
                      onChange={(e) => setPathForm({ ...pathForm, market_db: e.target.value })}
                    />
                  </Form.Item>
                  <Form.Item label="分析库 (DuckDB)">
                    <Input
                      value={pathForm.analytics_db}
                      onChange={(e) => setPathForm({ ...pathForm, analytics_db: e.target.value })}
                    />
                  </Form.Item>
                  <Form.Item label="原始缓存目录">
                    <Input
                      value={pathForm.raw_cache}
                      onChange={(e) => setPathForm({ ...pathForm, raw_cache: e.target.value })}
                    />
                  </Form.Item>
                  <Space>
                    <Button
                      type="primary"
                      icon={<CheckCircleOutlined />}
                      onClick={savePaths}
                      loading={saving}
                    >
                      保存
                    </Button>
                    <Button
                      icon={<FolderOpenOutlined />}
                      onClick={() => setMigrateModalOpen(true)}
                    >
                      迁移数据目录
                    </Button>
                  </Space>

                  <Divider />
                  <Title level={5}>路径详情</Title>
                  <Table
                    columns={pathColumns}
                    dataSource={pathData}
                    rowKey="key"
                    size="small"
                    pagination={false}
                  />
                </Form>
              </Card>
            ),
          },
          {
            key: 'scheduler',
            label: <span><ClockCircleOutlined /> 调度</span>,
            children: (
              <Card size="small">
                <Form layout="vertical" style={{ maxWidth: 500 }}>
                  <Form.Item label="启用自动调度">
                    <Switch
                      checked={schedulerForm.enabled}
                      onChange={(v) => setSchedulerForm({ ...schedulerForm, enabled: v })}
                    />
                  </Form.Item>
                  <Form.Item label="Cron 表达式">
                    <Input
                      value={schedulerForm.cron}
                      onChange={(e) => setSchedulerForm({ ...schedulerForm, cron: e.target.value })}
                      placeholder="30 18 * * 1-5"
                    />
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      格式：分 时 日 月 周（如 30 18 * * 1-5 = 工作日 18:30）
                    </Text>
                  </Form.Item>
                  <Form.Item label="时区">
                    <Input
                      value={schedulerForm.timezone}
                      onChange={(e) => setSchedulerForm({ ...schedulerForm, timezone: e.target.value })}
                    />
                  </Form.Item>
                  <Button
                    type="primary"
                    icon={<CheckCircleOutlined />}
                    onClick={saveScheduler}
                    loading={saving}
                  >
                    保存
                  </Button>
                </Form>
              </Card>
            ),
          },
          {
            key: 'hotspot',
            label: <span><FireOutlined /> 热点分析</span>,
            children: (
              <Card size="small">
                <Form layout="vertical" style={{ maxWidth: 500 }}>
                  <Form.Item label="启用热点分析">
                    <Switch
                      checked={hotspotForm.enabled}
                      onChange={(v) => setHotspotForm({ ...hotspotForm, enabled: v })}
                    />
                  </Form.Item>
                  <Row gutter={16}>
                    <Col span={12}>
                      <Form.Item label="LLM 批量大小">
                        <InputNumber
                          value={hotspotForm.batch_size}
                          onChange={(v) => setHotspotForm({ ...hotspotForm, batch_size: v ?? 8 })}
                          min={1} max={32}
                          style={{ width: '100%' }}
                        />
                      </Form.Item>
                    </Col>
                    <Col span={12}>
                      <Form.Item label="守护轮询间隔（秒）">
                        <InputNumber
                          value={hotspotForm.daemon_interval}
                          onChange={(v) => setHotspotForm({ ...hotspotForm, daemon_interval: v ?? 300 })}
                          min={60} max={3600} step={60}
                          style={{ width: '100%' }}
                        />
                      </Form.Item>
                    </Col>
                  </Row>
                  <Form.Item label="SimHash 去重阈值（汉明距离）">
                    <InputNumber
                      value={hotspotForm.simhash_threshold}
                      onChange={(v) => setHotspotForm({ ...hotspotForm, simhash_threshold: v ?? 3 })}
                      min={0} max={10}
                      style={{ width: '100%' }}
                    />
                  </Form.Item>
                  <Divider />
                  <Form.Item label="热点情绪融合比例 (alpha)">
                    <InputNumber
                      value={fusionForm.hotspot_alpha}
                      onChange={(v) => setFusionForm({ ...fusionForm, hotspot_alpha: v ?? 0.3 })}
                      min={0} max={1} step={0.05}
                      style={{ width: '100%' }}
                    />
                    <Text type="secondary" style={{ fontSize: 12 }}>
                      0 = 纯原有情绪，1 = 纯热点情绪，默认 0.3
                    </Text>
                  </Form.Item>
                  <Form.Item label="Regime 调节">
                    <Switch
                      checked={fusionForm.regime_adjust_enabled}
                      onChange={(v) => setFusionForm({ ...fusionForm, regime_adjust_enabled: v })}
                    />
                    <Text type="secondary" style={{ marginLeft: 8, fontSize: 12 }}>
                      市场极端情绪时缩放置信度
                    </Text>
                  </Form.Item>
                  <Space>
                    <Button
                      type="primary"
                      icon={<CheckCircleOutlined />}
                      onClick={saveHotspot}
                      loading={saving}
                    >
                      保存热点设置
                    </Button>
                    <Button
                      icon={<CheckCircleOutlined />}
                      onClick={saveFusion}
                      loading={saving}
                    >
                      保存融合参数
                    </Button>
                  </Space>
                </Form>
              </Card>
            ),
          },
        ]}
      />

      {/* 数据目录迁移确认对话框 */}
      <Modal
        title="迁移数据目录"
        open={migrateModalOpen}
        onOk={handleMigrate}
        onCancel={() => setMigrateModalOpen(false)}
        okText="确认迁移"
        cancelText="取消"
        okButtonProps={{ danger: true }}
      >
        <Alert
          type="warning"
          message="此操作将移动 DuckDB 数据库文件到新目录"
          description="迁移期间请勿运行数据更新。建议先备份。"
          showIcon
          style={{ marginBottom: 16 }}
        />
        <Input
          placeholder="新数据目录路径（如 D:/quant-data）"
          value={newDataDir}
          onChange={(e) => setNewDataDir(e.target.value)}
        />
      </Modal>
    </div>
  );
}
