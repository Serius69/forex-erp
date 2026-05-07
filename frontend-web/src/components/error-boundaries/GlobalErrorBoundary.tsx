// GlobalErrorBoundary — envuelve toda la aplicación
import React, { Component, ErrorInfo } from 'react';
import { AppCrashPage } from '../troubleshooting/AppCrashPage';
import { logErrorSync } from '../../services/errorLogger';
import { makeErrorId } from '../../services/errorTypes';

interface State {
  hasError: boolean;
  errorId:  string;
}

interface Props {
  children: React.ReactNode;
}

export class GlobalErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, errorId: '' };

  static getDerivedStateFromError(): Partial<State> {
    return { hasError: true, errorId: makeErrorId('GLOBAL') };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    logErrorSync(error, {
      errorType:      'GlobalBoundaryError',
      componentStack: info.componentStack ?? undefined,
      extra:          { boundary: 'global' },
    });
  }

  handleRetry = (): void => {
    this.setState({ hasError: false, errorId: '' });
  };

  render() {
    if (this.state.hasError) {
      return <AppCrashPage errorId={this.state.errorId} onRetry={this.handleRetry} />;
    }
    return this.props.children;
  }
}

export default GlobalErrorBoundary;
