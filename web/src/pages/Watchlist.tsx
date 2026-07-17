import { useEffect, useState } from 'react';
import { Card, Table, Empty, Modal, Form, InputNumber, Input, Button, Popconfirm, Space, Alert, message } from 'antd';
import { api, WatchItem, errMsg } from '../api/client';
import { COLORS } from '../theme';
import { PageHeader, PageLoading, dirTag } from '../components/common';

function fmt(v: number | null | undefined, digits: number) {
  return v == null || isNaN(v) ? '-' : v.toFixed(digits);
}

export default function Watchlist() {
  const [data, setData] = useState<WatchItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [open, setOpen] = useState(false);
  const [form] = Form.useForm();
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    setError(null);
    api.get('/watchlist')
      .then((r) => setData(r.data))
      .catch((e) => { setError(errMsg(e)); message.error('自选股加载失败'); })
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const onSubmit = async () => {
    const v = await form.validateFields();
    await api.post('/watchlist', v);
    setOpen(false);
    form.resetFields();
    load();
  };

  const onDelete = async (code: string) => {
    await api.delete(`/watchlist/${code}`);
    load();
  };

  if (loading) return <PageLoading tip="正在加载自选股…" />;

  const columns = [
    { title: '代码', dataIndex: 'code' },
    { title: '名称', dataIndex: 'name' },
    { title: '成本', dataIndex: 'cost_price', render: (v: number | null | undefined) => fmt(v, 2) },
    { title: '现价', dataIndex: 'current_price', render: (v?: number) => fmt(v, 2) },
    { title: '持仓盈亏%', dataIndex: 'pnl_pct', render: (v?: number) => (v == null ? '-' : <span style={{ color: v >= 0 ? COLORS.up : COLORS.down }}>{v.toFixed(2)}%</span>) },
    { title: '信号', dataIndex: 'direction', render: (d?: number) => (d == null ? '-' : dirTag(d)) },
    { title: '置信度', dataIndex: 'confidence', render: (v?: number) => fmt(v, 2) },
    {
      title: '操作',
      render: (_: unknown, r: WatchItem) => (
        <Popconfirm title="删除该自选股？" onConfirm={() => onDelete(r.code)}>
          <Button size="small" danger>删除</Button>
        </Popconfirm>
      ),
    },
  ];

  return (
    <div className="page">
      <PageHeader title="自选股（记账持仓）" />
      {error && (
        <Alert style={{ marginBottom: 16 }} type="error" showIcon message="自选股加载失败" description={error} />
      )}
      <Space style={{ marginBottom: 16 }}>
        <Button type="primary" onClick={() => setOpen(true)}>添加持仓</Button>
      </Space>
      {data.length === 0 ? (
        <Card><Empty description="暂无自选股，点击添加" /></Card>
      ) : (
        <Card>
          <Table size="small" rowKey="code" columns={columns} dataSource={data} pagination={false} scroll={{ x: 'max-content' }} />
        </Card>
      )}
      <Modal title="添加自选股持仓" open={open} onOk={onSubmit} onCancel={() => setOpen(false)} okText="保存">
        <Form form={form} layout="vertical">
          <Form.Item name="code" label="代码" rules={[{ required: true, message: '请输入代码' }]}>
            <Input placeholder="如 600519.SH" />
          </Form.Item>
          <Form.Item name="name" label="名称">
            <Input placeholder="如 贵州茅台" />
          </Form.Item>
          <Form.Item name="cost_price" label="成本价" rules={[{ required: true, message: '请输入成本价' }]}>
            <InputNumber min={0.01} style={{ width: '100%' }} />
          </Form.Item>
          <Form.Item name="shares" label="持仓数量" rules={[{ required: true, message: '请输入持仓数量' }]}>
            <InputNumber min={0} style={{ width: '100%' }} />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
}
