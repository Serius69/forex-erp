// SectionErrorBoundary — envuelve secciones críticas (tablas, gráficas, widgets)
import React, { Component, ErrorInfo } from 'react';
import { SectionError } from '../troubleshooting/SectionError';
import { logErrorSync } from '../../services/errorLogger';

interface State { hasError: boolean }
interface Props {
  children:    React.ReactNode;
  sectionName?: string;
  compact?:    boolean;
  fallback?:   React.ReactNode;
}

export class SectionErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    logErrorSync(error, {
      errorType:      'SectionBoundaryError',
      componentStack: info.componentStack ?? undefined,
      extra:          { boundary: 'section', section: this.props.sectionName },
    });
  }

  handleRetry = (): void => {
    this.setState({ hasError: false });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return <>{this.props.fallback}</>;
      return (
        <SectionError
          type="load_failed"
          entityName={this.props.sectionName}
          onRetry={this.handleRetry}
          compact={this.props.compact}
        />
      );
    }
    return this.props.children;
  }
}

export default SectionErrorBoundary;
