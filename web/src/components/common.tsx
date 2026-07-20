import type { ReactNode } from 'react';
import { Card, Row, Col, Statistic, Tag, Typography, Skeleton } from 'antd';
import type { MarketSentimentView } from '../api/client';
import {
  STATUS_META, REGIME_COLOR, REGIME_STATE_COLOR, SIGNAL_COLOR, subBar,
} from '../constants';

const { Text } = Typography;

// ══════════════════════════════════════════
//  Direction Tag: A-stock "red-up / green-down"
//  Uses new semantic color system
// ══════════════════════════════════════════
export function dirTag(d?: number) {
  if (d === 1) return <Tag className="ant-tag-red">看多</Tag>;
  if (d === -1) return <Tag className="ant-tag-green">看空</Tag>;
  return <Tag className="ant-tag-default">中性</Tag>;
}

// ══════════════════════════════════════════
//  Status Tag (pipeline status)
// ══════════════════════════════════════════
export function StatusTag({ status }: { status?: string }) {
  const m = (status && STATUS_META[status]) || STATUS_META.idle;
  const colorClass =
    m.color === 'green' ? 'ant-tag-green' :
    m.color === 'red' ? 'ant-tag-red' :
    m.color === 'blue' ? 'ant-tag-blue' :
    m.color === 'orange' ? 'ant-tag-orange' : 'ant-tag-default';
  return <Tag className={colorClass}>{m.label}</Tag>;
}

// ══════════════════════════════════════════
//  Sentiment Index Card (Dashboard & Monitor shared)
//  Premium card with refined data presentation
// ══════════════════════════════════════════
export function SentimentCard({ data }: { data?: MarketSentimentView }) {
  if (!data || !data.available) {
    return (
      <Card
        className="metric-card"
        title={
          <span style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}>
            市场情绪指数（T1/T2/T3）
          </span>
        }
      >
        <Text type="secondary" style={{ fontSize: 13 }}>
          {data?.error || '暂无市场情绪数据（运行一次盘后流水线后生成）'}
        </Text>
      </Card>
    );
  }

  const ms = data;

  return (
    <Card
      className="metric-card"
      title={
        <span style={{ fontFamily: "var(--font-display)", fontWeight: 600 }}>
          市场情绪指数（T1/T2/T3）
        </span>
      }
    >
      {/* Primary metric + regime tags row */}
      <Row gutter={[20, 12]} align="middle" style={{ marginBottom: 14 }}>
        <Col xs={24} sm={9}>
          <Statistic
            title={<span style={{ fontSize: 12, color: "var(--text-secondary)" }}>综合情绪指数</span>}
            value={ms.index_value ?? '-'}
            precision={1}
            valueStyle={{
              fontSize: 28,
              fontFamily: "var(--font-mono)",
              fontWeight: 700,
              letterSpacing: "-0.02em",
            }}
          />
        </Col>
        <Col xs={24} sm={15}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
            <Tag
              className={
                REGIME_COLOR[ms.regime || ''] === "green"
                  ? "ant-tag-green"
                  : REGIME_COLOR[ms.regime || ''] === "red"
                    ? "ant-tag-red"
                    : REGIME_COLOR[ms.regime || ''] === "orange"
                      ? "ant-tag-orange"
                      : "ant-tag-default"
              }
            >
              {ms.regime || '-'}
            </Tag>
            <Tag
              className={
                SIGNAL_COLOR[ms.signal || ''] === "green"
                  ? "ant-tag-green"
                  : SIGNAL_COLOR[ms.signal || ''] === "red"
                    ? "ant-tag-red"
                    : SIGNAL_COLOR[ms.signal || ''] === "orange"
                      ? "ant-tag-orange"
                      : "ant-tag-default"
              }
            >
              {ms.signal || '-'}
            </Tag>
          </div>

          <div style={{ marginTop: 8 }}>
            <Text
              type="secondary"
              style={{ fontSize: 11.5, fontFamily: "var(--font-mono)", letterSpacing: "0.01em" }}
            >
              温度计 <span style={{ color: "var(--text-primary)" }}>{ms.thermometer ?? '-'}</span>
              {" · "}GSISI <span style={{ color: "var(--text-primary)" }}>{ms.gsisi ?? '-'}</span>
            </Text>
          </div>

          <div style={{ marginTop: 7, display: "flex", flexWrap: "wrap", gap: 6, alignItems: "center" }}>
            <Tag
              className={
                REGIME_STATE_COLOR[ms.regime_state || ''] === "success"
                  ? "ant-tag-green"
                  : REGIME_STATE_COLOR[ms.regime_state || ''] === "error"
                    ? "ant-tag-red"
                    : REGIME_STATE_COLOR[ms.regime_state || ''] === "warning"
                      ? "ant-tag-orange"
                      : "ant-tag-blue"
              }
            >
              状态 {ms.regime_state || '-'}
            </Tag>
            <Text
              type="secondary"
              style={{ fontSize: 11.5, fontFamily: "var(--font-mono)" }}
            >
              置信缩缩 x{(ms.regime_scale ?? 1).toFixed(2)}
            </Text>
          </div>
        </Col>
      </Row>

      {/* Sub-bar progress indicators */}
      <div style={{ marginTop: 4 }}>
        {subBar('量能分', ms.sub_volume)}
        {subBar('价格分', ms.sub_price)}
        {subBar('资金分', ms.sub_money)}
        {subBar('估值分', ms.sub_valuation)}
        {subBar('风险溢价分', ms.sub_riskpremium)}
      </div>

      {/* Footer timestamp */}
      <div style={{ marginTop: 10 }}>
        <Text
          type="secondary"
          style={{ fontSize: 11.5, fontFamily: "var(--font-mono)", letterSpacing: "0.01em" }}
        >
          更新日 {ms.latest_date}
        </Text>
      </div>
    </Card>
  );
}

// ══════════════════════════════════════════
//  Unified Page Header
//  Clear typographic hierarchy
// ══════════════════════════════════════════
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

// ══════════════════════════════════════════
//  Page Loading Skeleton (shimmer animation)
//  Replaces bare Spin with structured skeleton
// ══════════════════════════════════════════
export function PageLoading({ tip }: { tip?: string }) {
  return (
    <div className="page">
      {/* Title skeleton */}
      <Skeleton.Input active style={{ width: 220, height: 28, borderRadius: "var(--radius-sm)" }} />

      <div style={{ marginTop: 18 }}>
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
        <div className="page-loading" style={{ minHeight: 0, marginTop: 10 }}>
          <Text type="secondary" style={{ fontSize: 12.5, fontFamily: "var(--font-mono)" }}>
            {tip}
          </Text>
        </div>
      )}
    </div>
  );
}

// ══════════════════════════════════════════
//  Composed Empty State
//  Better than a plain text message
// ══════════════════════════════════════════
export function EmptyHint({ description }: { description: string }) {
  return (
    <div
      className="page-loading"
      style={{
        minHeight: "40vh",
        gap: 12,
      }}
    >
      <div
        style={{
          width: 56,
          height: 56,
          borderRadius: "50%",
          background: "var(--bg-elevated)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          opacity: 0.6,
        }}
      >
        <span style={{ fontSize: 24, opacity: 0.35 }}>--</span>
      </div>
      <Text type="secondary" style={{ fontSize: 13.5, maxWidth: 320, textAlign: "center" }}>
        {description}
      </Text>
    </div>
  );
}
