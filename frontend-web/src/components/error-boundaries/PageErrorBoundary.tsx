// PageErrorBoundary — envuelve cada página/ruta
import React, { Component, ErrorInfo } from 'react';
import { PageErrorPage, PageErrorType } from '../troubleshooting/PageErrorPage';
import { logErrorSync } from '../../services/errorLogger';
import { makeErrorId } from '../../services/errorTypes';

function httpStatusToType(status?: number): PageErrorType {
  if (!status) return 'server_error';
  if (status === 401 || status === 419) return 'session_expired';
  if (status === 403)  return 'forbidden';
  if (status === 404)  return 'not_found';
  if (status === 408 || status === 504) return 'timeout';
  if (status === 503)  return 'maintenance';
  if (status >= 500)   return 'server_error';
  return 'server_error';
}

interface State {
  hasError:  boolean;
  errorId:   string;
  errorType: PageErrorType;
}

interface Props {
  children:    React.ReactNode;
  pageName?:   string;
  errorType?:  PageErrorType;
}

export class PageErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, errorId: '', errorType: 'server_error' };

  static getDerivedStateFromError(error: Error & { status?: number }): Partial<State> {
    return {
      hasError:  true,
      errorId:   makeErrorId('PAGE'),
      errorType: httpStatusToType(error.status),
    };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    logErrorSync(error, {
      errorType:      'PageBoundaryError',
      componentStack: info.componentStack ?? undefined,
      extra:          { boundary: 'page', page: this.props.pageName },
    });
  }

  handleRetry = (): void => {
    this.setState({ hasError: false, errorId: '', errorType: 'server_error' });
  };

  render() {
    if (this.state.hasError) {
      return (
        <PageErrorPage
          type={this.props.errorType ?? this.state.errorType}
          errorId={this.state.errorId}
          onRetry={this.handleRetry}
        />
      );
    }
    return this.props.children;
  }
}

export default PageErrorBoundary;
