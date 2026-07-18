import React, { useEffect, useState, useRef } from 'react';
import { Card, Table, Tag, Typography, Spin, Row, Col, Statistic, DatePicker, Select, Empty, message } from 'antd';
import { FireOutlined, ThunderboltOutlined, AlertOutlined } from '@ant-design/icons';
import { api } from '../api/client';
import dayjs from 'dayjs';

const { Title, Paragraph, Text } = Typography;

interface HotspotItem {
  ts: string;
  source: string;
  title: string;
  topic: string;
  sentiment: string;
  sentiment_score: number;
  impact: string;
  impact_score: number;
  related_sectors: string;
  related_codes: string;
  reasoning: string;
  composite_score: number;
  created_at?: string;
}

interface HotspotStats {
  daily_stats: {
    ts_date: string;
    total: number;
    positive: number;
    negative: number;
    neutral: number;
    high_impact: number;
    avg_score: number | null;
  }[];
  total: number;
}

interface HotspotDigest {
  date: string;
  content: string;
  total_count: number;
  positive: number;
  negative: number;
  neutral: number;
}

const sentimentColor: Record<string, string> = {
  '利好': 'green',
  '利空': 'red',
  '中性': 'default',
};

const impactColor: Record<string, string> = {
  '高': 'volcano',
  '中': 'orange',
  '低': 'default',
};

export default function Hotspot() {
  const [loading, setLoading] = useState(true);
  const [items, setItems] = useState<HotspotItem[]>([]);
  const [stats, setStats] = useState<HotspotStats | null>(null);
  const [digest, setDigest] = useState<HotspotDigest | null>(null);
  const [selectedDate, setSelectedDate] = useState<dayjs.Dayjs | null>(null);
  const [filterSentiment, setFilterSentiment] = useState<string | undefined>(undefined);
  const [filterImpact, setFilterImpact] = useState<string | undefined>(undefined);
  const eventSourceRef = useRef<EventSource | null>(null);

  const fetchData = async (date?: string) => {
    setLoading(true);
    try {
      const params: Record<string, any> = { limit: 200 };
      if (date) params.date = date;

      const [itemsRes, statsRes, digestRes] = await Promise.all([
        api.get<{ items: HotspotItem[]; total: number }>('/hotspot/latest', { params }),
        api.get<HotspotStats>('/hotspot/stats', { params: { days: 14 } }),
        api.get<HotspotDigest>('/hotspot/digest', { params: date ? { date } : {} }),
      ]);

      let filtered = itemsRes.data.items;
      if (filterSentiment) filtered = filtered.filter((i) => i.sentiment === filterSentiment);
      if (filterImpact) filtered = filtered.filter((i) => i.impact === filterImpact);

      setItems(filtered);
      setStats(statsRes.data);
      setDigest(digestRes.data);
    } catch (err: any) {
      message.error('热点数据加载失败');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData(selectedDate?.format('YYYY-MM-DD'));

    // SSE 实时推送
    const es = new EventSource('/api/hotspot/stream');
    eventSourceRef.current = es;
    es.onmessage = (e) => {
      try {
        const item: HotspotItem = JSON.parse(e.data);
        setItems((prev) => [item, ...prev].slice(0, 200));
      } catch {
        // ignore parse errors
      }
    };
    es.onerror = () => {
      // 静默处理，EventSource 会自动重连
    };

    return () => {
      es.close();
      eventSourceRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterSentiment, filterImpact]);

  const handleDateChange = (date: dayjs.Dayjs | null) => {
    setSelectedDate(date);
    fetchData(date?.format('YYYY-MM-DD'));
  };

  const columns = [
    {
      title: '时间',
      dataIndex: 'ts',
      key: 'ts',
      width: 140,
      render: (ts: string) => dayjs(ts).format('MM-DD HH:mm'),
    },
    {
      title: '来源',
      dataIndex: 'source',
      key: 'source',
      width: 100,
      render: (s: string) => <Tag>{s}</Tag>,
    },
    {
      title: '标题',
      dataIndex: 'title',
      key: 'title',
      ellipsis: true,
      render: (title: string, record: HotspotItem) => (
        <div>
          <Text strong>{record.topic}</Text>
          <br />
          <Text type="secondary" style={{ fontSize: 12 }}>{title}</Text>
        </div>
      ),
    },
    {
      title: '情感',
      dataIndex: 'sentiment',
      key: 'sentiment',
      width: 80,
      filters: [
        { text: '利好', value: '利好' },
        { text: '利空', value: '利空' },
        { text: '中性', value: '中性' },
      ],
      onFilter: (value: any, record: HotspotItem) => record.sentiment === value,
      render: (s: string) => <Tag color={sentimentColor[s]}>{s}</Tag>,
    },
    {
      title: '分值',
      dataIndex: 'sentiment_score',
      key: 'sentiment_score',
      width: 70,
      sorter: (a: HotspotItem, b: HotspotItem) => a.sentiment_score - b.sentiment_score,
      render: (v: number) => (
        <span style={{ color: v > 0 ? '#52c41a' : v < 0 ? '#ff4d4f' : '#999' }}>
          {v.toFixed(2)}
        </span>
      ),
    },
    {
      title: '影响',
      dataIndex: 'impact',
      key: 'impact',
      width: 70,
      render: (s: string) => <Tag color={impactColor[s]}>{s}</Tag>,
    },
    {
      title: '关联板块',
      dataIndex: 'related_sectors',
      key: 'related_sectors',
      width: 150,
      render: (s: string) =>
        s ? s.split(',').map((t) => <Tag key={t} color="blue">{t}</Tag>) : '-',
    },
    {
      title: '关联标的',
      dataIndex: 'related_codes',
      key: 'related_codes',
      width: 120,
      render: (s: string) =>
        s ? s.split(',').slice(0, 3).map((c) => <Tag key={c}>{c}</Tag>) : '-',
    },
    {
      title: '依据',
      dataIndex: 'reasoning',
      key: 'reasoning',
      ellipsis: true,
      render: (s: string) => <Text type="secondary" style={{ fontSize: 12 }}>{s}</Text>,
    },
  ];

  return (
    <div style={{ padding: 24 }}>
      <Title level={3}>
        <FireOutlined /> 热点语义分析
      </Title>

      {/* 统计卡片 */}
      {stats && stats.daily_stats.length > 0 && (
        <Row gutter={16} style={{ marginBottom: 16 }}>
          <Col span={4}>
            <Card size="small">
              <Statistic
                title="热点总数"
                value={stats.total}
                prefix={<ThunderboltOutlined />}
              />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small">
              <Statistic
                title="利好"
                value={stats.daily_stats.reduce((s, d) => s + d.positive, 0)}
                valueStyle={{ color: '#52c41a' }}
              />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small">
              <Statistic
                title="利空"
                value={stats.daily_stats.reduce((s, d) => s + d.negative, 0)}
                valueStyle={{ color: '#ff4d4f' }}
                prefix={<AlertOutlined />}
              />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small">
              <Statistic
                title="高影响力"
                value={stats.daily_stats.reduce((s, d) => s + d.high_impact, 0)}
                valueStyle={{ color: '#fa8c16' }}
              />
            </Card>
          </Col>
          <Col span={4}>
            <Card size="small">
              <Statistic
                title="平均分值"
                value={
                  stats.daily_stats
                    .filter((d) => d.avg_score !== null)
                    .reduce((s, d) => s + (d.avg_score || 0), 0) /
                  (stats.daily_stats.filter((d) => d.avg_score !== null).length || 1)
                }
                precision={3}
              />
            </Card>
          </Col>
        </Row>
      )}

      {/* 筛选控件 */}
      <Row gutter={16} style={{ marginBottom: 16 }}>
        <Col>
          <DatePicker
            value={selectedDate}
            onChange={handleDateChange}
            placeholder="选择日期"
            allowClear
          />
        </Col>
        <Col>
          <Select
            placeholder="情感筛选"
            allowClear
            style={{ width: 120 }}
            value={filterSentiment}
            onChange={setFilterSentiment}
            options={[
              { value: '利好', label: '利好' },
              { value: '利空', label: '利空' },
              { value: '中性', label: '中性' },
            ]}
          />
        </Col>
        <Col>
          <Select
            placeholder="影响力筛选"
            allowClear
            style={{ width: 120 }}
            value={filterImpact}
            onChange={setFilterImpact}
            options={[
              { value: '高', label: '高' },
              { value: '中', label: '中' },
              { value: '低', label: '低' },
            ]}
          />
        </Col>
      </Row>

      {/* 热点摘要 */}
      {digest && digest.content && (
        <Card
          size="small"
          title="热点语义摘要"
          style={{ marginBottom: 16 }}
          extra={
            digest.total_count != null && (
              <Text type="secondary">
                共 {digest.total_count} 条 · 利好 {digest.positive} · 利空 {digest.negative} · 中性 {digest.neutral}
              </Text>
            )
          }
        >
          <div style={{ whiteSpace: 'pre-wrap', maxHeight: 200, overflow: 'auto' }}>
            <ReactMarkdown>{digest.content}</ReactMarkdown>
          </div>
        </Card>
      )}

      {/* 热点列表 */}
      <Card size="small">
        <Spin spinning={loading}>
          {items.length === 0 && !loading ? (
            <Empty description="暂无热点数据" />
          ) : (
            <Table
              columns={columns}
              dataSource={items}
              rowKey={(r) => `${r.ts}_${r.source}_${r.title}`}
              size="small"
              pagination={{ pageSize: 50, showSizeChanger: false }}
              scroll={{ x: 1000 }}
            />
          )}
        </Spin>
      </Card>
    </div>
  );
}

// 轻量 Markdown 渲染（避免引入 react-markdown 依赖）
function ReactMarkdown({ children }: { children: string }) {
  const lines = children.split('\n');
  return (
    <div>
      {lines.map((line, i) => {
        if (line.startsWith('# ')) return <Title key={i} level={4}>{line.slice(2)}</Title>;
        if (line.startsWith('## ')) return <Title key={i} level={5}>{line.slice(3)}</Title>;
        if (line.startsWith('- ')) return <div key={i} style={{ marginLeft: 16 }}>• {line.slice(2)}</div>;
        if (line.trim() === '') return <br key={i} />;
        return <Paragraph key={i} style={{ marginBottom: 4 }}>{line}</Paragraph>;
      })}
    </div>
  );
}
