// Servicio centralizado de logging de errores frontend → backend
import { makeErrorId } from './errorTypes';

const IS_DEV = import.meta.env.DEV;
const ENDPOINT = '/api/logs/frontend-error/';

interface FrontendErrorPayload {
  error_id:        string;
  error_type:      string;
  message:         string;
  stack?:          string;
  component_stack?: string;
  url:             string;
  user_agent:      string;
  timestamp:       string;
  user_id?:        number | null;
  company_id?:     number | null;
  extra?:          Record<string, unknown>;
}

let _userId:    number | null = null;
let _companyId: number | null = null;

export function setErrorLoggerContext(userId: number | null, companyId: number | null): void {
  _userId    = userId;
  _companyId = companyId;
}

function sanitizeStack(stack: string | undefined): string {
  if (!stack) return '';
  // Never send tokens or passwords in stack traces
  const lower = stack.toLowerCase();
  const sensitive = ['bearer ', 'token=', 'password', 'authorization', 'refresh'];
  if (sensitive.some((s) => lower.includes(s))) return '[sanitized]';
  return stack.slice(0, 3000);
}

export async function logError(
  error:          Error | unknown,
  options: {
    errorType?:      string;
    componentStack?: string;
    extra?:          Record<string, unknown>;
  } = {},
): Promise<void> {
  const err = error instanceof Error ? error : new Error(String(error));

  const payload: FrontendErrorPayload = {
    error_id:        makeErrorId('FE'),
    error_type:      options.errorType ?? err.name ?? 'Error',
    message:         err.message.slice(0, 1000),
    stack:           sanitizeStack(err.stack),
    component_stack: options.componentStack?.slice(0, 2000),
    url:             window.location.href,
    user_agent:      navigator.userAgent.slice(0, 200),
    timestamp:       new Date().toISOString(),
    user_id:         _userId,
    company_id:      _companyId,
    extra:           options.extra,
  };

  if (IS_DEV) {
    console.error(
      `%c[ErrorLogger] %c${payload.error_type}: ${payload.message}`,
      'color: #ff4444; font-weight: bold',
      'color: inherit',
      '\nError ID:', payload.error_id,
      '\nStack:', err.stack,
      options.extra ? '\nExtra:' : '',
      options.extra ?? '',
    );
    return;
  }

  try {
    // Fire-and-forget — no interrumpe la UI si el log falla
    await fetch(ENDPOINT, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
      // keepalive: permite enviar incluso si la página se está cerrando
      keepalive: true,
    });
  } catch {
    // Silenciar fallos de logging — no crear ciclos de error
  }
}

export function logErrorSync(error: Error | unknown, extra?: Record<string, unknown>): void {
  logError(error, { extra }).catch(() => {});
}
