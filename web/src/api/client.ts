const BASE = '';

type ResourceListParams = {
  page?: number;
  pageSize?: number;
  search?: string;
};

function formatErrorValue(value: unknown, fallback: string): string {
  if (typeof value === 'string' && value) return value;
  if (value === null || value === undefined) return fallback;
  try {
    return JSON.stringify(value);
  } catch {
    return fallback;
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const opts: RequestInit = {
    method,
    headers: { 'Content-Type': 'application/json' },
  };
  if (body !== undefined) {
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(`${BASE}${path}`, opts);
  if (resp.status === 204) return undefined as T;
  const contentType = resp.headers.get('content-type') || '';
  let data: unknown = null;
  try {
    data = contentType.includes('application/json')
      ? await resp.json()
      : await resp.text();
  } catch {
    data = await resp.text().catch(() => '');
  }
  const fallback = `HTTP ${resp.status}`;
  const message = typeof data === 'object' && data !== null
    ? formatErrorValue(
        (data as { detail?: unknown; error?: unknown }).detail
          ?? (data as { detail?: unknown; error?: unknown }).error,
        fallback,
      )
    : typeof data === 'string' && data
      ? data
      : fallback;
  if (!resp.ok) throw new Error(message);
  return data as T;
}

export const api = {
  createConnection: (conn: unknown) => request<unknown>('POST', '/api/connections', conn),
  listConnections: () => request<unknown[]>('GET', '/api/connections'),
  updateConnection: (id: string, conn: unknown) => request<unknown>('PUT', `/api/connections/${id}`, conn),
  deleteConnection: (id: string) => request<void>('DELETE', `/api/connections/${id}`),
  testConnection: (id: string) => request<{ ok: boolean; error?: string }>('POST', `/api/connections/${id}/test`),

  listResourceTypes: (connId: string) => request<unknown[]>('GET', `/api/connections/${connId}/resources`),
  listResources: (connId: string, type: string, params: ResourceListParams = {}) => {
    const query = new URLSearchParams();
    if (params.page !== undefined) query.set('page', String(params.page));
    if (params.pageSize !== undefined) query.set('page_size', String(params.pageSize));
    if (params.search) query.set('search', params.search);
    const suffix = query.size > 0 ? `?${query.toString()}` : '';
    return request<{ count: number; results: unknown[]; page: number; page_size: number }>(
      'GET',
      `/api/connections/${connId}/resources/${type}${suffix}`,
    );
  },

  runCleanup: (connId: string) => request<{ job_id: string }>('POST', `/api/connections/${connId}/cleanup`),
  runExport: (connId: string) => request<{ job_id: string }>('POST', `/api/connections/${connId}/export`),

  migrationPreview: (sourceId: string, destinationId: string) =>
    request<{ job_id: string }>('POST', '/api/migrate/preview', { source_id: sourceId, destination_id: destinationId }),
  getMigrationPreview: (jobId: string) =>
    request<unknown>('GET', `/api/migrate/preview/${jobId}`),
  migrationRun: (sourceId: string, destinationId: string, previewJobId: string) =>
    request<{ job_id: string }>('POST', '/api/migrate/run', {
      source_id: sourceId,
      destination_id: destinationId,
      job_id: previewJobId,
    }),

  clearMigrationState: () => request<{ cleared_progress: number; deleted_mappings: number }>('POST', '/api/migrate/clear-state'),
  getExclusions: () => request<unknown>('GET', '/api/exclusions'),

  listJobs: () => request<unknown[]>('GET', '/api/jobs'),
  getJob: (id: string) => request<unknown>('GET', `/api/jobs/${id}`),
  cancelJob: (jobId: string) => request<{ status: string }>('POST', `/api/jobs/${jobId}/cancel`),
};

export function createJobLogSocket(jobId: string, onMessage: (line: string) => void, onClose?: (status: string) => void): WebSocket {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${window.location.host}/ws/jobs/${jobId}/logs`);
  ws.onmessage = (e) => onMessage(e.data);
  ws.onclose = (e) => onClose?.(e.reason || 'closed');
  return ws;
}
