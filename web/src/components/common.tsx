import type { ReactNode } from 'react';
import { Card, Row, Col, Statistic, Tag, Typography, Skeleton } from 'antd';
import type { MarketSentimentView } from '../api/client';
import {
  STATUS_META, REGIME_COLOR, REGIME_STATE_COLOR, SIGNAL_COLOR, subBar,
} from '../constants';

const { Text } = Typography;

/** 方向标签：A股「红涨绿跌」→ 看多红 / 看空绿 / 中性灰 */
export function dirTag(d?: number) {
  if (d === 1) return <Tag color="red">看多</Tag>;
  if (d === -1) return <Tag color="green">看空</Tag>;
  return <Tag>中性</Tag>;
}

/** 状态标签（根据 STATUS_META 渲染） */
export function StatusTag({ status }: { status?: string }) {
  const m = (status && STATUS_META[status]) || STATUS_META.idle;
  return <Tag color={m.color}>{m.label}</Tag>;
}

/** 市场情绪指数卡（Dashboard 与 Monitor 共用，避免重复实现） */
export function SentimentCard({ data }: { data?: MarketSentimentView }) {
  if (!data || !data.available) {
    return (
      <Card className="metric-card" title="市场情绪指数（T1/T2/T3）">
        <Text type="secondary">
          {data?.error ? data.error : '暂无市场情绪数据（运行一次盘后流水线后生成）'}
        </Text>
      </Card>
    );
  }
  const ms = data;
  return (
    <Card className="metric-card" title="市场情绪指数（T1/T2/T3）">
      <Row gutter={16} align="middle">
        <Col xs={24} sm={10}>
          <Statistic title="综合情绪指数" value={ms.index_value ?? '-'} precision={1} />
        </Col>
        <Col xs={24} sm={14}>
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
    </Card>
  );
}

/** 统一页头：标题 + 可选副标题/右侧操作区 */
export function PageHeader({
  title,
  subtitle,
  extra,
}: {
  title: string;
  subtitle?: string;
  extra?: ReactNode;
}) {
  return (
    <div className="page-header">
      <div>
        <h2 className="page-title">{title}</h2>
        {subtitle && <div className="page-subtitle">{subtitle}</div>}
      </div>
      {extra && <div className="page-header-extra">{extra}</div>}
    </div>
  );
}

/** 整页加载态（骨架屏，替代裸 Spin） */
export function PageLoading({ tip }: { tip?: string }) {
  return (
    <div className="page">
      <Skeleton.Input active style={{ width: 220, height: 30 }} />
      <div style={{ marginTop: 16 }}>
        <Row gutter={[16, 16]}>
          {[0, 1, 2].map((i) => (
            <Col xs={24} md={8} key={i}>
              <Card className="metric-card">
                <Skeleton active paragraph={{ rows: 3 }} title={false} />
              </Card>
            </Col>
          ))}
        </Row>
        <Card className="metric-card" style={{ marginTop: 16 }}>
          <Skeleton active paragraph={{ rows: 6 }} />
        </Card>
      </div>
      {tip && (
        <div className="page-loading" style={{ minHeight: 0, marginTop: 8 }}>
          <Text type="secondary">{tip}</Text>
        </div>
      )}
    </div>
  );
}

/** 整页空态 */
export function EmptyHint({ description }: { description: string }) {
  return (
    <div className="page-loading">
      <Text type="secondary">{description}</Text>
    </div>
  );
}
