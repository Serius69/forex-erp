import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import './i18n/index';  // initialize i18next before rendering
import App from './App';
import { GlobalErrorBoundary } from './components/error-boundaries/GlobalErrorBoundary';

const root = ReactDOM.createRoot(
  document.getElementById('root') as HTMLElement
);
root.render(
  <React.StrictMode>
    <GlobalErrorBoundary>
      <App />
    </GlobalErrorBoundary>
  </React.StrictMode>
);
