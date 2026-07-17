import { Component, type ReactNode } from 'react';
import { Result, Button } from 'antd';

interface State {
  hasError: boolean;
  message?: string;
}

// 全局错误边界：避免单个页面异常导致整站白屏
export default class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error.message };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // 仅记录，便于排查；不向用户暴露堆栈
    console.error('UI 渲染异常：', error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <Result
          status="error"
          title="页面渲染出错"
          subTitle={this.state.message || '界面发生未预期错误，请重试。'}
          extra={
            <Button type="primary" onClick={() => window.location.reload()}>
              重新加载
            </Button>
          }
        />
      );
    }
    return this.props.children;
  }
}
