const DEFAULT_BASE_URL = 'http://127.0.0.1:8009/api/v1';
const RUNTIME_BASE_URL_KEY = 'llmkeyrotator_api_base_url';
const ADMIN_TOKEN_KEY = 'llmkeyrotator_admin_token';

export type LoginResponse = {
  access_token: string;
  token_type: 'bearer';
  expires_in_minutes: number;
};

export type AdminSetupStatusResponse = {
  setup_required: boolean;
  password_configured: boolean;
  password_override_configured: boolean;
};

export type AdminPasswordChangeResponse = {
  updated: boolean;
};

export type HealthResponse = {
  status: string;
  service: string;
  version: string;
  schema_version: string;
};

export type GlobalMetrics = {
  total_requests: number;
  success_rate: number;
  avg_latency_ms: number;
  total_tokens_consumed: number;
  active_keys_count: number;
  cooldown_keys_count: number;
  total_rotations_triggered: number;
};

export type ProjectMetrics = {
  app_token_id: number;
  app_name: string;
  environment: string;
  requests_count: number;
  total_tokens_consumed: number;
  avg_latency_ms: number;
};

export type ModelQueueStrategy = 'ordered' | 'smart' | 'latency';

export type ModelQueueCandidate = {
  id: number;
  queue_id: number;
  provider: string;
  model_name: string;
  position: number;
  is_active: boolean;
  score: number;
  failure_count: number;
  success_count: number;
  avg_latency_ms: number;
  last_used_at: string | null;
  last_error_at: string | null;
  last_success_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ModelQueue = {
  id: number;
  name: string;
  description: string | null;
  strategy: ModelQueueStrategy;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  candidates: ModelQueueCandidate[];
};

export type MetricsTimeseriesBucket = {
  bucket_start: string;
  bucket_end: string;
  requests_count: number;
  success_count: number;
  error_count: number;
  total_tokens_consumed: number;
  avg_latency_ms: number;
  total_rotations_triggered: number;
};

export type MetricsTimeseries = {
  window: string;
  granularity: string;
  buckets: MetricsTimeseriesBucket[];
};

export type OverviewModelUsage = {
  model_name: string;
  requests_count: number;
  success_count: number;
  error_count: number;
  total_tokens_consumed: number;
  avg_latency_ms: number;
  total_rotations_triggered: number;
};

export type OverviewSummary = {
  total_requests: number;
  success_rate: number;
  avg_latency_ms: number;
  total_tokens_consumed: number;
  total_rotations_triggered: number;
};

export type OverviewTelemetry = {
  protocol_in_counts: Record<string, number>;
  protocol_out_counts: Record<string, number>;
  route_kind_counts: Record<string, number>;
  tool_calling_count: number;
};

export type OverviewDetail = {
  context_type: 'app_token' | 'provider' | 'provider_key' | 'queue';
  context_id: number | null;
  context_label: string;
  window: string;
  granularity: string;
  summary: OverviewSummary;
  telemetry: OverviewTelemetry;
  timeseries: MetricsTimeseries;
  models: OverviewModelUsage[];
};

export type ProviderKey = {
  id: number;
  name: string;
  description: string | null;
  provider: string;
  status: 'ACTIVE' | 'COOLDOWN' | 'INVALID' | 'SUSPENDED_BILLING';
  blocked_until: string | null;
  failure_count: number;
  created_at: string;
  updated_at: string;
  masked_token: string;
};

export type ProviderKeyPeekResponse = {
  token: string;
};

export type AppToken = {
  id: number;
  name: string;
  environment: 'development' | 'staging' | 'production';
  rpm_limit: number | null;
  is_active: boolean;
  created_at: string;
  masked_token: string;
};

export type AppTokenCreateResult = AppToken & {
  token: string;
};

export type UsageLog = {
  id: number;
  app_token_id: number;
  app_token_name?: string;
  provider_key_id: number | null;
  provider_key_name?: string;
  protocol_in: string;
  protocol_out: string;
  route_kind: string;
  queue_name?: string | null;
  model_requested: string;
  provider_used: string;
  resolved_model?: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  latency_ms: number;
  status_code: number;
  was_rotated: boolean;
  tool_calling: boolean;
  error_message: string | null;
  created_at: string;
};

export type UsageLogPage = {
  items: UsageLog[];
  total: number;
  limit: number;
  offset: number;
};

export type RuntimeConfig = {
  host: string;
  port: number;
  api_base_url: string;
  restart_required: boolean;
};

export type AlertSettings = {
  key: string;
  telegram_enabled: boolean;
  telegram_bot_token_configured: boolean;
  telegram_chat_id: string | null;
  alert_proxy_failures: boolean;
  alert_queue_exhausted: boolean;
  alert_provider_pool_exhausted: boolean;
  alert_provider_key_status_changes: boolean;
  created_at: string;
  updated_at: string;
};

export type AlertTelegramTestResponse = {
  sent: boolean;
  detail: string;
};

export function apiBaseUrl() {
  if (typeof localStorage !== 'undefined') {
    const runtimeBaseUrl = localStorage.getItem(RUNTIME_BASE_URL_KEY);
    if (runtimeBaseUrl) {
      return runtimeBaseUrl;
    }
  }
  return import.meta.env.VITE_API_BASE_URL || DEFAULT_BASE_URL;
}

export function setRuntimeApiBaseUrl(apiBaseUrl: string) {
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem(RUNTIME_BASE_URL_KEY, apiBaseUrl);
  }
}

export function getStoredAdminToken() {
  if (typeof localStorage === 'undefined') {
    return '';
  }

  return localStorage.getItem(ADMIN_TOKEN_KEY) ?? '';
}

export function setStoredAdminToken(token: string) {
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem(ADMIN_TOKEN_KEY, token);
  }
}

export function clearStoredAdminToken() {
  if (typeof localStorage !== 'undefined') {
    localStorage.removeItem(ADMIN_TOKEN_KEY);
  }
}

export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch(`${apiBaseUrl().replace(/\/api\/v1$/, '')}/health`);

  if (!response.ok) {
    throw new Error('Backend health check failed');
  }

  return response.json();
}

export async function loginAdmin(password: string): Promise<LoginResponse> {
  const response = await fetch(`${apiBaseUrl()}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ password })
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || 'Login failed');
  }

  return response.json();
}

export async function fetchAdminSetupStatus(): Promise<AdminSetupStatusResponse> {
  const response = await fetch(`${apiBaseUrl()}/auth/setup`);

  if (!response.ok) {
    throw new Error('Failed to load admin setup status');
  }

  return response.json();
}

export async function setupAdminPassword(payload: {
  password: string;
  confirm_password: string;
}): Promise<LoginResponse> {
  const response = await fetch(`${apiBaseUrl()}/auth/setup`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || 'Failed to complete admin setup');
  }

  return response.json();
}

export async function logoutAdmin(token: string): Promise<void> {
  const response = await fetch(`${apiBaseUrl()}/auth/logout`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` }
  });

  if (!response.ok) {
    throw new Error('Failed to logout');
  }
}

export async function changeAdminPassword(
  token: string,
  payload: {
    password: string;
    confirm_password: string;
  }
): Promise<AdminPasswordChangeResponse> {
  const response = await fetch(`${apiBaseUrl()}/auth/password`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || 'Failed to update admin password');
  }

  return response.json();
}

export async function fetchGlobalMetrics(
  token: string,
  range: '1h' | '24h' | '7d' | '30d' = '24h'
): Promise<GlobalMetrics> {
  const response = await fetch(`${apiBaseUrl()}/observability/metrics/global?range=${range}`, {
    headers: { Authorization: `Bearer ${token}` }
  });

  if (!response.ok) {
    throw new Error('Failed to load global metrics');
  }

  return response.json();
}

export async function fetchProjectMetrics(
  token: string,
  range: '1h' | '24h' | '7d' | '30d' = '24h'
): Promise<ProjectMetrics[]> {
  const response = await fetch(`${apiBaseUrl()}/observability/metrics/projects?range=${range}`, {
    headers: { Authorization: `Bearer ${token}` }
  });

  if (!response.ok) {
    throw new Error('Failed to load project metrics');
  }

  return response.json();
}

export async function fetchModelQueues(token: string): Promise<ModelQueue[]> {
  const response = await fetch(`${apiBaseUrl()}/model-queues`, {
    headers: { Authorization: `Bearer ${token}` }
  });

  if (!response.ok) {
    throw new Error('Failed to load model queues');
  }

  return response.json();
}

export async function createModelQueue(
  token: string,
  payload: {
    name: string;
    description?: string | null;
    strategy: ModelQueueStrategy;
  }
): Promise<ModelQueue> {
  const response = await fetch(`${apiBaseUrl()}/model-queues`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || 'Failed to create model queue');
  }

  return response.json();
}

export async function updateModelQueue(
  token: string,
  queueId: number,
  payload: {
    name?: string;
    description?: string | null;
    strategy?: ModelQueueStrategy;
    is_active?: boolean;
  }
): Promise<ModelQueue> {
  const response = await fetch(`${apiBaseUrl()}/model-queues/${queueId}`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || 'Failed to update model queue');
  }

  return response.json();
}

export async function deleteModelQueue(token: string, queueId: number): Promise<void> {
  const response = await fetch(`${apiBaseUrl()}/model-queues/${queueId}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` }
  });

  if (!response.ok) {
    throw new Error('Failed to delete model queue');
  }
}

export async function createModelQueueCandidate(
  token: string,
  queueId: number,
  payload: {
    provider: string;
    model_name: string;
    position?: number;
    is_active?: boolean;
  }
): Promise<ModelQueueCandidate> {
  const response = await fetch(`${apiBaseUrl()}/model-queues/${queueId}/candidates`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || 'Failed to create model queue candidate');
  }

  return response.json();
}

export async function updateModelQueueCandidate(
  token: string,
  candidateId: number,
  payload: {
    provider?: string;
    model_name?: string;
    position?: number;
    is_active?: boolean;
  }
): Promise<ModelQueueCandidate> {
  const response = await fetch(`${apiBaseUrl()}/model-queues/candidates/${candidateId}`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || 'Failed to update model queue candidate');
  }

  return response.json();
}

export async function deleteModelQueueCandidate(token: string, candidateId: number): Promise<void> {
  const response = await fetch(`${apiBaseUrl()}/model-queues/candidates/${candidateId}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` }
  });

  if (!response.ok) {
    throw new Error('Failed to delete model queue candidate');
  }
}

export async function fetchMetricsTimeseries(token: string, range = '24h'): Promise<MetricsTimeseries> {
  const params = new URLSearchParams();
  params.set('range', range);

  const response = await fetch(`${apiBaseUrl()}/observability/metrics/timeseries?${params.toString()}`, {
    headers: { Authorization: `Bearer ${token}` }
  });

  if (!response.ok) {
    throw new Error('Failed to load metrics timeseries');
  }

  return response.json();
}

export async function fetchAppTokenOverview(
  token: string,
  appTokenId: number,
  range: '1h' | '24h' | '7d' | '30d' = '24h'
): Promise<OverviewDetail> {
  const response = await fetch(`${apiBaseUrl()}/observability/overview/app-tokens/${appTokenId}?range=${range}`, {
    headers: { Authorization: `Bearer ${token}` }
  });

  if (!response.ok) {
    throw new Error('Failed to load app token overview');
  }

  return response.json();
}

export async function fetchProviderKeyOverview(
  token: string,
  providerKeyId: number,
  range: '1h' | '24h' | '7d' | '30d' = '24h'
): Promise<OverviewDetail> {
  const response = await fetch(`${apiBaseUrl()}/observability/overview/provider-keys/${providerKeyId}?range=${range}`, {
    headers: { Authorization: `Bearer ${token}` }
  });

  if (!response.ok) {
    throw new Error('Failed to load provider key overview');
  }

  return response.json();
}

export async function fetchQueueOverview(
  token: string,
  queueName: string,
  range: '1h' | '24h' | '7d' | '30d' = '24h'
): Promise<OverviewDetail> {
  const response = await fetch(`${apiBaseUrl()}/observability/overview/model-queues/${encodeURIComponent(queueName)}?range=${range}`, {
    headers: { Authorization: `Bearer ${token}` }
  });

  if (!response.ok) {
    throw new Error('Failed to load queue overview');
  }

  return response.json();
}

export async function fetchProviderKeys(
  token: string,
  filters?: { provider?: string; status?: ProviderKey['status'] | '' }
): Promise<ProviderKey[]> {
  const params = new URLSearchParams();
  if (filters?.provider) {
    params.set('provider', filters.provider);
  }
  if (filters?.status) {
    params.set('status', filters.status);
  }

  const response = await fetch(`${apiBaseUrl()}/provider-keys${params.toString() ? `?${params.toString()}` : ''}`, {
    headers: { Authorization: `Bearer ${token}` }
  });

  if (!response.ok) {
    throw new Error('Failed to load provider keys');
  }

  return response.json();
}

export async function createProviderKey(
  token: string,
  payload: {
    name: string;
    description?: string;
    provider: string;
    tokenValue: string;
  }
): Promise<ProviderKey> {
  const response = await fetch(`${apiBaseUrl()}/provider-keys`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      name: payload.name,
      description: payload.description || null,
      provider: payload.provider,
      token: payload.tokenValue
    })
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || 'Failed to create provider key');
  }

  return response.json();
}

export async function deleteProviderKey(token: string, providerKeyId: number): Promise<void> {
  const response = await fetch(`${apiBaseUrl()}/provider-keys/${providerKeyId}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` }
  });

  if (!response.ok) {
    throw new Error('Failed to delete provider key');
  }
}

export async function updateProviderKey(
  token: string,
  providerKeyId: number,
  payload: {
    status?: ProviderKey['status'];
    blocked_until?: string | null;
    failure_count?: number;
    name?: string;
    provider?: string;
    description?: string | null;
    tokenValue?: string;
  }
): Promise<ProviderKey> {
  const response = await fetch(`${apiBaseUrl()}/provider-keys/${providerKeyId}`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({
      ...payload,
      token: payload.tokenValue
    })
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || 'Failed to update provider key');
  }

  return response.json();
}

export async function peekProviderKey(
  token: string,
  providerKeyId: number,
  adminPassword: string
): Promise<ProviderKeyPeekResponse> {
  const response = await fetch(`${apiBaseUrl()}/provider-keys/${providerKeyId}/peek`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ admin_password: adminPassword })
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || 'Failed to peek provider key');
  }

  return response.json();
}

export async function fetchAppTokens(token: string, active: boolean | null = null): Promise<AppToken[]> {
  const params = new URLSearchParams();
  if (active !== null) {
    params.set('active', String(active));
  }

  const response = await fetch(`${apiBaseUrl()}/app-tokens${params.toString() ? `?${params.toString()}` : ''}`, {
    headers: { Authorization: `Bearer ${token}` }
  });

  if (!response.ok) {
    throw new Error('Failed to load app tokens');
  }

  return response.json();
}

export async function createAppToken(
  token: string,
  payload: {
    name: string;
    environment: AppToken['environment'];
    rpm_limit?: number | null;
  }
): Promise<AppTokenCreateResult> {
  const response = await fetch(`${apiBaseUrl()}/app-tokens`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || 'Failed to create app token');
  }

  return response.json();
}

export async function peekAppToken(token: string, appTokenId: number): Promise<AppTokenCreateResult> {
  const response = await fetch(`${apiBaseUrl()}/app-tokens/${appTokenId}/peek`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` }
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || 'Failed to peek app token');
  }

  return response.json();
}

export async function rotateAppToken(token: string, appTokenId: number): Promise<AppTokenCreateResult> {
  const response = await fetch(`${apiBaseUrl()}/app-tokens/${appTokenId}/rotate`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` }
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || 'Failed to rotate app token');
  }

  return response.json();
}

export async function deleteAppToken(token: string, appTokenId: number): Promise<void> {
  const response = await fetch(`${apiBaseUrl()}/app-tokens/${appTokenId}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` }
  });

  if (!response.ok) {
    throw new Error('Failed to delete app token');
  }
}

export async function updateAppToken(
  token: string,
  appTokenId: number,
  payload: {
    is_active?: boolean;
    environment?: AppToken['environment'];
    rpm_limit?: number | null;
    name?: string;
  }
): Promise<AppToken> {
  const response = await fetch(`${apiBaseUrl()}/app-tokens/${appTokenId}`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || 'Failed to update app token');
  }

  return response.json();
}

export async function fetchUsageLogs(
  token: string,
  limit = 10,
  filters?: {
    appTokenId?: number | null;
    providerKeyId?: number | null;
    queueName?: string | null;
    protocolIn?: string | null;
    protocolOut?: string | null;
    routeKind?: string | null;
    toolCalling?: boolean | null;
    offset?: number;
  }
): Promise<UsageLogPage> {
  const params = new URLSearchParams();
  params.set('limit', String(limit));
  params.set('offset', String(filters?.offset ?? 0));
  if (filters?.appTokenId !== undefined && filters.appTokenId !== null) {
    params.set('app_token_id', String(filters.appTokenId));
  }
  if (filters?.providerKeyId !== undefined && filters.providerKeyId !== null) {
    params.set('provider_key_id', String(filters.providerKeyId));
  }
  if (filters?.queueName) {
    params.set('queue_name', filters.queueName);
  }
  if (filters?.protocolIn) {
    params.set('protocol_in', filters.protocolIn);
  }
  if (filters?.protocolOut) {
    params.set('protocol_out', filters.protocolOut);
  }
  if (filters?.routeKind) {
    params.set('route_kind', filters.routeKind);
  }
  if (filters?.toolCalling !== undefined && filters.toolCalling !== null) {
    params.set('tool_calling', String(filters.toolCalling));
  }

  const response = await fetch(`${apiBaseUrl()}/usage-logs?${params.toString()}`, {
    headers: { Authorization: `Bearer ${token}` }
  });

  if (!response.ok) {
    throw new Error('Failed to load usage logs');
  }

  return response.json();
}

export async function fetchRuntimeConfig(token: string): Promise<RuntimeConfig> {
  const response = await fetch(`${apiBaseUrl()}/admin/runtime`, {
    headers: { Authorization: `Bearer ${token}` }
  });

  if (!response.ok) {
    throw new Error('Failed to load runtime config');
  }

  return response.json();
}

export async function updateRuntimeConfig(
  token: string,
  payload: { host?: string; port?: number }
): Promise<RuntimeConfig> {
  const response = await fetch(`${apiBaseUrl()}/admin/runtime`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || 'Failed to update runtime config');
  }

  return response.json();
}

export async function fetchAlertSettings(token: string): Promise<AlertSettings> {
  const response = await fetch(`${apiBaseUrl()}/admin/alerts`, {
    headers: { Authorization: `Bearer ${token}` }
  });

  if (!response.ok) {
    throw new Error('Failed to load alert settings');
  }

  return response.json();
}

export async function updateAlertSettings(
  token: string,
  payload: {
    telegram_enabled?: boolean;
    telegram_bot_token?: string | null;
    telegram_chat_id?: string | null;
    alert_proxy_failures?: boolean;
    alert_queue_exhausted?: boolean;
    alert_provider_pool_exhausted?: boolean;
    alert_provider_key_status_changes?: boolean;
  }
): Promise<AlertSettings> {
  const response = await fetch(`${apiBaseUrl()}/admin/alerts`, {
    method: 'PATCH',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || 'Failed to update alert settings');
  }

  return response.json();
}

export async function sendTelegramTestAlert(
  token: string,
  payload: {
    telegram_bot_token?: string | null;
    telegram_chat_id?: string | null;
  }
): Promise<AlertTelegramTestResponse> {
  const response = await fetch(`${apiBaseUrl()}/admin/alerts/test`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(payload)
  });

  if (!response.ok) {
    const detail = await response.text();
    throw new Error(detail || 'Failed to send Telegram test alert');
  }

  return response.json();
}
