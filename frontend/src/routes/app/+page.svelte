<script lang="ts">
  import { goto } from '$app/navigation';
  import { onDestroy, onMount } from 'svelte';
  import {
    fetchAlertSettings,
    createAppToken,
    createModelQueue,
    createModelQueueCandidate,
    createProviderKey,
    clearStoredAdminToken,
    deleteAppToken,
    deleteModelQueue,
    deleteModelQueueCandidate,
    deleteProviderKey,
    fetchAppTokens,
    fetchGlobalMetrics,
    fetchHealth,
    fetchMetricsTimeseries,
    fetchModelQueues,
    fetchProjectMetrics,
    fetchProviderKeys,
    fetchRuntimeConfig,
    fetchUsageLogs,
    getStoredAdminToken,
    peekProviderKey as peekProviderKeyApi,
    peekAppToken as peekAppTokenApi,
    logoutAdmin,
    sendTelegramTestAlert,
    setRuntimeApiBaseUrl,
    setStoredAdminToken,
    updateAppToken,
    rotateAppToken as rotateAppTokenApi,
    updateAlertSettings,
    updateModelQueue,
    updateModelQueueCandidate,
    updateProviderKey,
    updateRuntimeConfig,
    type AppToken,
    type AppTokenCreateResult,
    type AlertSettings,
    type GlobalMetrics,
    type MetricsTimeseries,
    type ModelQueue,
    type ModelQueueCandidate,
    type ModelQueueStrategy,
    type ProjectMetrics,
    type ProviderKey,
    type RuntimeConfig,
    type UsageLog,
    type UsageLogPage
  } from '$lib/api';
  import { formatOverviewTimeLabel } from '$lib/formatting';
  import { overviewRouteHref } from '$lib/overview';
  import { applyThemeMode, getStoredThemeMode, setStoredThemeMode, type ThemeMode } from '$lib/theme';
  import {
    LayoutDashboard,
    Key,
    Coins,
    BarChart2,
    Settings,
    ChevronDown,
    PanelLeftClose,
    PanelLeftOpen,
    BookOpenText,
    SquareTerminal,
    Copy,
    Pencil,
    Trash2
  } from 'lucide-svelte';
  import { Line, Doughnut, Bar } from 'svelte-chartjs';
  import { Chart, Title, Tooltip, LineElement, PointElement, CategoryScale, LinearScale, Filler, ArcElement, BarElement, Legend, type ChartOptions } from 'chart.js';

  Chart.register(Title, Tooltip, Legend, LineElement, PointElement, CategoryScale, LinearScale, Filler, ArcElement, BarElement);

  type SectionKey = 'overview' | 'keys' | 'tokens' | 'queues' | 'usage' | 'runtime';
  type UiPreferences = {
    activeSection: SectionKey;
    providerKeyProviderFilter: string;
    providerKeyStatusFilter: ProviderKey['status'] | '';
    providerKeySearch: string;
    appTokenActiveFilter: '' | 'true' | 'false';
    appTokenSearch: string;
    usageAppTokenFilter: string;
    usageProviderKeyFilter: string;
    usageQueueFilter: string;
    usageProtocolInFilter: string;
    usageProtocolOutFilter: string;
    usageRouteKindFilter: string;
    usageToolCallingFilter: '' | 'true' | 'false';
    usageLimit: number;
    usagePage: number;
    activityFilter: 'all' | 'success' | 'error' | 'info';
    activitySearch: string;
    autoRefreshEnabled: boolean;
  };
  type Notice = {
    id: number;
    type: 'success' | 'error' | 'info';
    title: string;
    detail: string;
    at: string;
  };

  const UI_PREFERENCES_KEY = 'llmkeyrotator_admin_ui_preferences';
  const UI_ACTIVITY_KEY = 'llmkeyrotator_admin_activity_log';

  const sections: Array<{ key: SectionKey; label: string; icon: typeof LayoutDashboard }> = [
    { key: 'overview', label: 'Overview', icon: LayoutDashboard },
    { key: 'keys', label: 'Provider Keys', icon: Key },
    { key: 'tokens', label: 'App Tokens', icon: Coins },
    { key: 'queues', label: 'Model Queues', icon: BarChart2 },
    { key: 'usage', label: 'Usage', icon: BarChart2 },
    { key: 'runtime', label: 'Runtime', icon: Settings }
  ];

  import { activeSection as activeSectionStore, topbarTitle, refreshTrigger } from '$lib/stores';

  let activeSection: SectionKey = 'overview';
  let telegramTestReady = false;
  $: activeSection = $activeSectionStore;
  $: if (activeSection !== $activeSectionStore) {
    activeSectionStore.set(activeSection);
  }
  $: {
    const matched = sections.find((s) => s.key === activeSection);
    if (matched) {
      topbarTitle.set(matched.label);
    }
  }
  $: telegramTestReady = Boolean(
    (alertTelegramChatId.trim() || alertSettings?.telegram_chat_id) &&
      (alertTelegramBotToken.trim() || alertSettings?.telegram_bot_token_configured)
  );
  let token = '';
  let themeMode: ThemeMode = 'system';
  let loading = false;
  let actionBusy = false;
  let globalMetrics: GlobalMetrics | null = null;
  let overviewTimeseries: MetricsTimeseries | null = null;
  let projectMetrics: ProjectMetrics[] = [];
  let providerKeys: ProviderKey[] = [];
  let appTokens: AppToken[] = [];
  let modelQueues: ModelQueue[] = [];
  let usageLogs: UsageLog[] = [];
  let runtimeConfig: RuntimeConfig | null = null;
  let alertSettings: AlertSettings | null = null;
  let backendHealth: { status: string; service: string } | null = null;
  let metricsError = '';
  let runtimeError = '';
  let alertError = '';
  let runtimeNotice = '';
  let restartPending = false;
  let lastRefreshedAt: string | null = null;
  let refreshTimer: ReturnType<typeof setInterval> | null = null;
  let healthTimer: ReturnType<typeof setInterval> | null = null;
  let healthError = '';
  let notices: Notice[] = [];
  let activityLog: Notice[] = [];
  let activityFilter: 'all' | 'success' | 'error' | 'info' = 'all';
  let activitySearch = '';
  let autoRefreshEnabled = true;
  let noticeSequence = 0;
  let sidebarCollapsed = false;
  let showProviderKeyModal = false;
  let showAppTokenModal = false;
  let showModelQueueModal = false;

  let runtimeHost = '127.0.0.1';
  let runtimePort = 8009;
  let alertTelegramEnabled = false;
  let alertTelegramBotToken = '';
  let alertTelegramChatId = '';
  let alertProxyFailures = true;
  let alertQueueExhausted = true;
  let alertProviderPoolExhausted = true;
  let alertProviderKeyStatusChanges = true;
  let alertTestBusy = false;

  let providerName = '';
  let providerType = 'openai';
  let providerDescription = '';
  let providerSecret = '';
  let selectedProviderKeyId: number | null = null;
  let selectedProviderKeyName = '';
  let selectedProviderKeyProvider = 'openai';
  let selectedProviderKeyDescription = '';
  let providerKeyProviderFilter = '';
  let providerKeyStatusFilter: ProviderKey['status'] | '' = '';
  let providerKeySearch = '';
  let selectedProviderKeyIds: number[] = [];
  let peekProviderKeyId: number | null = null;
  let peekAdminPassword = '';
  let peekResult = '';
  let peekError = '';

  let appName = '';
  let appEnvironment: AppToken['environment'] = 'development';
  let appRateLimit = '';
  let selectedAppTokenId: number | null = null;
  let selectedAppTokenName = '';
  let selectedAppTokenEnvironment: AppToken['environment'] = 'development';
  let selectedAppTokenRateLimit = '';
  let selectedAppTokenIsActive = true;
  let appTokenActiveFilter: '' | 'true' | 'false' = '';
  let appTokenSearch = '';
  let selectedAppTokenIds: number[] = [];

  let queueName = '';
  let queueDescription = '';
  let queueStrategy: ModelQueueStrategy = 'ordered';
  let queueSearch = '';
  let queueModalMode: 'create' | 'edit' = 'create';
  let selectedQueueId: number | null = null;
  let selectedQueueCandidateId: number | null = null;
  let selectedQueueCandidateProvider = 'google';
  let selectedQueueCandidateModelName = '';
  let selectedQueueCandidatePosition = 0;
  let selectedQueueCandidateIsActive = true;
  let showQueueCandidateModal = false;

  let usageAppTokenFilter = '';
  let usageProviderKeyFilter = '';
  let usageQueueFilter = '';
  let usageProtocolInFilter = '';
  let usageProtocolOutFilter = '';
  let usageRouteKindFilter = '';
  let usageToolCallingFilter: '' | 'true' | 'false' = '';
  let usageLimit = 10;
  let usagePage = 1;
  let usageLogPage: UsageLogPage | null = null;
  let selectedUsageLog: UsageLog | null = null;
  let showUsageFilters = false;
  let overviewRange: '1h' | '24h' | '7d' | '30d' = '24h';

  let lastCreatedAppToken: AppTokenCreateResult | null = null;
  let selectedAppTokenSecret: AppTokenCreateResult | null = null;
  let isHydrated = false;
  let themeMediaQuery: MediaQueryList | null = null;
  let themeMediaQueryHandler: (() => void) | null = null;

  function pushNotice(type: Notice['type'], title: string, detail: string) {
    const id = ++noticeSequence;
    const at = new Date().toISOString();
    const entry = { id, type, title, detail, at };
    notices = [entry, ...notices].slice(0, 6);
    activityLog = [entry, ...activityLog].slice(0, 12);
    saveActivityLog();
    window.setTimeout(() => {
      notices = notices.filter((notice) => notice.id !== id);
    }, 6000);
  }

  function clearActivityLog() {
    activityLog = [];
    saveActivityLog();
  }

  function setActivityFilter(nextFilter: 'all' | 'success' | 'error' | 'info') {
    activityFilter = nextFilter;
  }

  function setUsagePage(nextPage: number) {
    usagePage = Math.max(1, nextPage);
    if (token) {
      void loadDashboard(token);
    }
  }

  function toggleAutoRefresh() {
    autoRefreshEnabled = !autoRefreshEnabled;
  }

  function handleThemeModeChange() {
    setStoredThemeMode(themeMode);
    applyThemeMode(themeMode);
  }

  $: filteredProviderKeys = providerKeys.filter((providerKey) => {
    const matchesSearch = providerKeySearch
      ? `${providerKey.name} ${providerKey.provider} ${providerKey.status}`.toLowerCase().includes(providerKeySearch.toLowerCase())
      : true;
    return matchesSearch;
  });

  $: filteredAppTokens = appTokens.filter((appToken) => {
    const matchesSearch = appTokenSearch
      ? `${appToken.name} ${appToken.environment}`.toLowerCase().includes(appTokenSearch.toLowerCase())
      : true;
    return matchesSearch;
  });

  $: filteredModelQueues = modelQueues.filter((queue) => {
    const matchesSearch = queueSearch
      ? `${queue.name} ${queue.description ?? ''} ${queue.strategy}`.toLowerCase().includes(queueSearch.toLowerCase())
      : true;
    return matchesSearch;
  });

  $: selectedProviderKey = selectedProviderKeyId === null
    ? null
    : providerKeys.find((providerKey) => providerKey.id === selectedProviderKeyId) ?? null;

  $: selectedAppToken = selectedAppTokenId === null
    ? null
    : appTokens.find((appToken) => appToken.id === selectedAppTokenId) ?? null;

  $: selectedQueue = selectedQueueId === null
    ? null
    : modelQueues.find((queue) => queue.id === selectedQueueId) ?? null;

  $: selectedQueueCandidate = selectedQueueId === null || selectedQueueCandidateId === null
    ? null
    : selectedQueue?.candidates.find((candidate) => candidate.id === selectedQueueCandidateId) ?? null;

  $: usageTotalLogs = usageLogPage?.total ?? 0;
  $: usageCurrentPage = usageLogPage ? Math.floor(usageLogPage.offset / usageLogPage.limit) + 1 : usagePage;
  $: usageTotalPages = usageLogPage ? Math.max(1, Math.ceil(usageLogPage.total / usageLogPage.limit)) : 1;
  $: usageStartIndex = usageLogPage && usageLogPage.total > 0 ? usageLogPage.offset + 1 : 0;
  $: usageEndIndex = usageLogPage ? Math.min(usageLogPage.offset + usageLogPage.items.length, usageLogPage.total) : 0;
  $: usageAppTokenCounts = usageLogs.reduce<Record<string, number>>((counts, log) => {
    const key = log.app_token_name ?? 'Unknown app';
    counts[key] = (counts[key] ?? 0) + 1;
    return counts;
  }, {});
  $: usageProviderKeyCounts = usageLogs.reduce<Record<string, number>>((counts, log) => {
    const key = log.provider_key_name ?? 'Unknown key';
    counts[key] = (counts[key] ?? 0) + 1;
    return counts;
  }, {});
  $: usageProviderCounts = usageLogs.reduce<Record<string, number>>((counts, log) => {
    counts[log.provider_used] = (counts[log.provider_used] ?? 0) + 1;
    return counts;
  }, {});
  $: usageModelCounts = usageLogs.reduce<Record<string, number>>((counts, log) => {
    const key = log.resolved_model ?? log.model_requested;
    counts[key] = (counts[key] ?? 0) + 1;
    return counts;
  }, {});

  function formatTopMetric(counts: Record<string, number>) {
    const entries = Object.entries(counts).sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
    if (!entries.length) {
      return 'None';
    }
    const [name, count] = entries[0];
    return `${name} ${count}`;
  }

  $: filteredActivityLog = activityFilter === 'all'
    ? activityLog
    : activityLog.filter((activity) => activity.type === activityFilter);

  $: searchedActivityLog = activitySearch
    ? filteredActivityLog.filter((activity) => {
        const query = activitySearch.toLowerCase();
        return `${activity.title} ${activity.detail} ${activity.type} ${activity.at}`.toLowerCase().includes(query);
      })
    : filteredActivityLog;

  $: groupedActivityLog = searchedActivityLog.reduce<Array<{ label: string; items: Notice[] }>>((groups, activity) => {
    const activityDate = new Date(activity.at);
    const today = new Date();
    const yesterday = new Date();
    yesterday.setDate(today.getDate() - 1);

    const sameDay =
      activityDate.getFullYear() === today.getFullYear() &&
      activityDate.getMonth() === today.getMonth() &&
      activityDate.getDate() === today.getDate();
    const sameYesterday =
      activityDate.getFullYear() === yesterday.getFullYear() &&
      activityDate.getMonth() === yesterday.getMonth() &&
      activityDate.getDate() === yesterday.getDate();

    const label = sameDay
      ? 'Today'
      : sameYesterday
        ? 'Yesterday'
        : new Intl.DateTimeFormat('en-US', { dateStyle: 'medium' }).format(activityDate);

    const group = groups.find((entry) => entry.label === label);
    if (group) {
      group.items.push(activity);
    } else {
      groups.push({ label, items: [activity] });
    }

    return groups;
  }, []);

  $: overviewBuckets = overviewTimeseries?.buckets ?? [];
  $: overviewRequestsTotal = overviewBuckets.reduce((total, bucket) => total + bucket.requests_count, 0);
  $: overviewTokensTotal = overviewBuckets.reduce((total, bucket) => total + bucket.total_tokens_consumed, 0);
  $: overviewLatencyAverage = overviewBuckets.length
    ? overviewBuckets.reduce((total, bucket) => total + bucket.avg_latency_ms, 0) / overviewBuckets.length
    : 0;
  $: overviewRequestsSeries = overviewBuckets.map((bucket) => bucket.requests_count);
  $: overviewErrorsSeries = overviewBuckets.map((bucket) => bucket.error_count);
  $: overviewLatencySeries = overviewBuckets.map((bucket) => bucket.avg_latency_ms);
  $: overviewTokensSeries = overviewBuckets.map((bucket) => bucket.total_tokens_consumed);

  $: overviewLabels = overviewBuckets.map((bucket) => {
    return formatOverviewTimeLabel(bucket.bucket_start, overviewRange);
  });

  const masterChartOptions: ChartOptions<'line'> = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: true, labels: { color: 'rgba(255,255,255,0.7)' } }, tooltip: { mode: 'index', intersect: false } },
    scales: { 
      x: { display: true, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: 'rgba(255,255,255,0.5)' } }, 
      y: { type: 'linear', display: true, position: 'left', min: 0, grid: { color: 'rgba(255,255,255,0.05)' }, ticks: { color: 'rgba(255,255,255,0.5)' } },
      y1: { type: 'linear', display: true, position: 'right', min: 0, grid: { drawOnChartArea: false }, ticks: { color: 'rgba(245, 158, 11, 0.5)' } }
    },
    elements: { point: { radius: 0, hitRadius: 10, hoverRadius: 4 } },
    interaction: { mode: 'nearest', axis: 'x', intersect: false }
  };

  $: masterChartData = {
    labels: overviewLabels,
    datasets: [
      {
        label: 'Requests',
        data: overviewRequestsSeries,
        borderColor: '#d8b858',
        backgroundColor: 'rgba(216, 184, 88, 0.15)',
        yAxisID: 'y',
        fill: true,
        tension: 0.3
      },
      {
        label: 'Errors',
        data: overviewErrorsSeries,
        borderColor: '#ef4444',
        backgroundColor: 'rgba(239, 68, 68, 0.15)',
        yAxisID: 'y',
        fill: true,
        tension: 0.3
      },
      {
        label: 'Latency (ms)',
        data: overviewLatencySeries,
        borderColor: '#f59e0b',
        backgroundColor: 'transparent',
        yAxisID: 'y1',
        borderDash: [5, 5],
        fill: false,
        tension: 0.3
      }
    ]
  };

  const biChartOptions: any = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: { legend: { display: true, position: 'bottom', labels: { color: 'rgba(255,255,255,0.7)', boxWidth: 12 } } }
  };

  const appBarChartOptions: any = {
    responsive: true,
    maintainAspectRatio: false,
    indexAxis: 'y',
    plugins: {
      legend: { display: true, position: 'bottom', labels: { color: 'rgba(255,255,255,0.72)', boxWidth: 12 } },
      tooltip: { mode: 'index', intersect: false }
    },
    scales: {
      x: {
        beginAtZero: true,
        grid: { color: 'rgba(255,255,255,0.05)' },
        ticks: { color: 'rgba(255,255,255,0.55)' }
      },
      y: {
        grid: { display: false },
        ticks: {
          color: 'rgba(255,255,255,0.68)',
          autoSkip: false,
          font: { size: 11 }
        }
      }
    },
    elements: { bar: { borderRadius: 6 } }
  };

  $: appRequestsData = {
    labels: projectMetrics.map((p) => p.app_name),
    datasets: [{
      data: projectMetrics.map((p) => p.requests_count),
      backgroundColor: ['#d8b858', '#ef4444', '#f59e0b', '#3b82f6', '#10b981', '#a8a29e'],
      borderColor: 'rgba(17,24,39,1)',
      borderWidth: 2
    }]
  };

  $: appTokensData = {
    labels: projectMetrics.map((p) => p.app_name),
    datasets: [{
      label: 'Tokens Consumed',
      data: projectMetrics.map((p) => p.total_tokens_consumed),
      backgroundColor: '#d8b858',
      borderRadius: 4
    }]
  };

  $: appLatencyData = {
    labels: projectMetrics.map((p) => p.app_name),
    datasets: [{
      label: 'Avg Latency (ms)',
      data: projectMetrics.map((p) => p.avg_latency_ms),
      backgroundColor: '#f59e0b',
      borderRadius: 4
    }]
  };

  function setOverviewRange(nextRange: '1h' | '24h' | '7d' | '30d') {
    overviewRange = nextRange;
    if (token) {
      void loadDashboard(token);
    }
  }

  function selectQueue(queue: ModelQueue) {
    selectedQueueId = queue.id;
    selectedQueueCandidateId = null;
    selectedQueueCandidateProvider = 'google';
    selectedQueueCandidateModelName = '';
    selectedQueueCandidatePosition = queue.candidates.length;
    selectedQueueCandidateIsActive = true;
  }

  function openCreateModelQueueModal() {
    queueModalMode = 'create';
    queueName = '';
    queueDescription = '';
    queueStrategy = 'ordered';
    showModelQueueModal = true;
  }

  function openEditModelQueueModal(queue: ModelQueue) {
    selectQueue(queue);
    queueModalMode = 'edit';
    queueName = queue.name;
    queueDescription = queue.description ?? '';
    queueStrategy = queue.strategy;
    showModelQueueModal = true;
  }

  function openProviderOverview(providerKey: ProviderKey) {
    void goto(overviewRouteHref('provider-key', providerKey.id));
  }

  function openAppTokenOverview(appToken: AppToken) {
    void goto(overviewRouteHref('app-token', appToken.id));
  }

  function openQueueOverview(queue: ModelQueue) {
    void goto(overviewRouteHref('model-queue', queue.name));
  }

  function selectQueueCandidate(candidate: ModelQueueCandidate) {
    selectedQueueCandidateId = candidate.id;
    selectedQueueCandidateProvider = candidate.provider;
    selectedQueueCandidateModelName = candidate.model_name;
    selectedQueueCandidatePosition = candidate.position;
    selectedQueueCandidateIsActive = candidate.is_active;
    showQueueCandidateModal = true;
  }

  async function loadDashboard(jwt: string) {
    loading = true;
    metricsError = '';
    runtimeError = '';
    try {
      const [global, timeseries, projects, providers, apps, queues, usage, runtime, alerts] = await Promise.all([
        fetchGlobalMetrics(jwt, overviewRange),
        fetchMetricsTimeseries(jwt, overviewRange),
        fetchProjectMetrics(jwt, overviewRange),
        fetchProviderKeys(jwt, { provider: providerKeyProviderFilter, status: providerKeyStatusFilter }),
        fetchAppTokens(jwt, appTokenActiveFilter === '' ? null : appTokenActiveFilter === 'true'),
        fetchModelQueues(jwt),
        fetchUsageLogs(jwt, usageLimit, {
          appTokenId: usageAppTokenFilter ? Number(usageAppTokenFilter) : null,
          providerKeyId: usageProviderKeyFilter ? Number(usageProviderKeyFilter) : null,
          queueName: usageQueueFilter || null,
          protocolIn: usageProtocolInFilter || null,
          protocolOut: usageProtocolOutFilter || null,
          routeKind: usageRouteKindFilter || null,
          toolCalling: usageToolCallingFilter === '' ? null : usageToolCallingFilter === 'true',
          offset: (usagePage - 1) * usageLimit
        }),
        fetchRuntimeConfig(jwt),
        fetchAlertSettings(jwt)
      ]);
      globalMetrics = global;
      overviewTimeseries = timeseries;
      projectMetrics = projects;
      providerKeys = providers;
      appTokens = apps;
      modelQueues = queues;
      if (modelQueues.length && (selectedQueueId === null || !modelQueues.some((queue) => queue.id === selectedQueueId))) {
        selectQueue(modelQueues[0]);
      }
      usageLogPage = usage;
      usageLogs = usage.items;
      runtimeConfig = runtime;
      runtimeHost = runtime.host;
      runtimePort = runtime.port;
      alertSettings = alerts;
      alertTelegramEnabled = alerts.telegram_enabled;
      alertTelegramBotToken = '';
      alertTelegramChatId = alerts.telegram_chat_id ?? '';
      alertProxyFailures = alerts.alert_proxy_failures;
      alertQueueExhausted = alerts.alert_queue_exhausted;
      alertProviderPoolExhausted = alerts.alert_provider_pool_exhausted;
      alertProviderKeyStatusChanges = alerts.alert_provider_key_status_changes;
      lastRefreshedAt = new Date().toISOString();
      token = jwt;
      setStoredAdminToken(jwt);
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'Failed to load dashboard';
    } finally {
      loading = false;
    }
  }

  async function refreshDashboard() {
    if (token) {
      await loadDashboard(token);
    }
  }

  async function refreshBackendHealth() {
    healthError = '';
    try {
      backendHealth = await fetchHealth();
    } catch (error) {
      backendHealth = null;
      healthError = error instanceof Error ? error.message : 'Backend health check failed';
    }
  }

  async function handleApplyFilters() {
    usagePage = 1;
    await refreshDashboard();
  }

  async function handleLogout() {
    if (token) {
      try {
        await logoutAdmin(token);
      } catch {
        // If the backend is unavailable, still end the local session.
      }
    }

    clearStoredAdminToken();
    token = '';
    await goto('/login');
  }

  async function handleRuntimeSave() {
    if (!token) {
      runtimeError = 'Login as admin before changing runtime settings.';
      return;
    }

    runtimeError = '';
    runtimeNotice = '';

    try {
      const updated = await updateRuntimeConfig(token, {
        host: runtimeHost,
        port: runtimePort
      });
      runtimeConfig = updated;
      runtimeHost = updated.host;
      runtimePort = updated.port;
      setRuntimeApiBaseUrl(updated.api_base_url);
      restartPending = true;
      runtimeNotice = 'Configuration saved. Restart the backend service, then reload this page to use the new port.';
      pushNotice('success', 'Runtime saved', `Backend configured for ${updated.host}:${updated.port}. Restart required.`);
    } catch (error) {
      runtimeError = error instanceof Error ? error.message : 'Failed to save runtime config';
      pushNotice('error', 'Runtime update failed', runtimeError);
    }
  }

  async function handleAlertSettingsSave() {
    if (!token) {
      alertError = 'Login as admin before changing alert settings.';
      return;
    }

    actionBusy = true;
    alertError = '';
    try {
      const payload: {
        telegram_enabled: boolean;
        telegram_bot_token?: string | null;
        telegram_chat_id: string | null;
        alert_proxy_failures: boolean;
        alert_queue_exhausted: boolean;
        alert_provider_pool_exhausted: boolean;
        alert_provider_key_status_changes: boolean;
      } = {
        telegram_enabled: alertTelegramEnabled,
        telegram_chat_id: alertTelegramChatId || null,
        alert_proxy_failures: alertProxyFailures,
        alert_queue_exhausted: alertQueueExhausted,
        alert_provider_pool_exhausted: alertProviderPoolExhausted,
        alert_provider_key_status_changes: alertProviderKeyStatusChanges
      };
      if (alertTelegramBotToken.trim()) {
        payload.telegram_bot_token = alertTelegramBotToken.trim();
      }

      const updated = await updateAlertSettings(token, payload);
      alertSettings = updated;
      alertTelegramEnabled = updated.telegram_enabled;
      alertTelegramBotToken = '';
      alertTelegramChatId = updated.telegram_chat_id ?? '';
      alertProxyFailures = updated.alert_proxy_failures;
      alertQueueExhausted = updated.alert_queue_exhausted;
      alertProviderPoolExhausted = updated.alert_provider_pool_exhausted;
      alertProviderKeyStatusChanges = updated.alert_provider_key_status_changes;
      pushNotice('success', 'Alert settings saved', 'Telegram notifications updated.');
    } catch (error) {
      alertError = error instanceof Error ? error.message : 'Failed to save alert settings';
      pushNotice('error', 'Alert settings update failed', alertError);
    } finally {
      actionBusy = false;
    }
  }

  async function handleTelegramTest() {
    if (!token) {
      alertError = 'Login as admin before testing Telegram alerts.';
      return;
    }

    if (!telegramTestReady) {
      alertError = 'Configure a Telegram chat ID and bot token before sending a test.';
      return;
    }

    alertTestBusy = true;
    alertError = '';
    try {
      const response = await sendTelegramTestAlert(token, {
        telegram_bot_token: alertTelegramBotToken.trim() || null,
        telegram_chat_id: alertTelegramChatId.trim() || null
      });
      pushNotice('success', 'Telegram test sent', response.detail);
    } catch (error) {
      alertError = error instanceof Error ? error.message : 'Failed to send Telegram test';
      pushNotice('error', 'Telegram test failed', alertError);
    } finally {
      alertTestBusy = false;
    }
  }

  async function handleCreateProviderKey() {
    if (!token || !providerName || !providerSecret) {
      return;
    }

    const createdName = providerName;
    actionBusy = true;
    metricsError = '';
    try {
      await createProviderKey(token, {
        name: providerName,
        description: providerDescription || undefined,
        provider: providerType,
        tokenValue: providerSecret
      });
      providerName = '';
      providerDescription = '';
      providerSecret = '';
      await loadDashboard(token);
      activeSection = 'keys';
      pushNotice('success', 'Provider key created', `${createdName} was added.`);
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'Failed to create provider key';
      pushNotice('error', 'Provider key creation failed', metricsError);
    } finally {
      actionBusy = false;
    }
  }

  async function handleDeleteProviderKey(providerKeyId: number) {
    if (!token) {
      return;
    }

    actionBusy = true;
    metricsError = '';
    try {
      await deleteProviderKey(token, providerKeyId);
      await loadDashboard(token);
      pushNotice('success', 'Provider key deleted', `Provider key #${providerKeyId} was removed.`);
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'Failed to delete provider key';
      pushNotice('error', 'Provider key delete failed', metricsError);
    } finally {
      actionBusy = false;
    }
  }

  async function handleSetProviderKeyStatus(providerKey: ProviderKey, status: ProviderKey['status']) {
    if (!token) {
      return;
    }

    actionBusy = true;
    metricsError = '';
    try {
      await updateProviderKey(token, providerKey.id, { status });
      await loadDashboard(token);
      pushNotice('success', 'Provider key updated', `${providerKey.name} moved to ${formatStatus(status)}.`);
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'Failed to update provider key';
      pushNotice('error', 'Provider key update failed', metricsError);
    } finally {
      actionBusy = false;
    }
  }

  async function handleBulkProviderKeyStatus(status: ProviderKey['status']) {
    if (!token || !selectedProviderKeyIds.length) {
      return;
    }

    const selectedCount = selectedProviderKeyIds.length;
    actionBusy = true;
    metricsError = '';
    try {
      for (const providerKeyId of [...selectedProviderKeyIds]) {
        await updateProviderKey(token, providerKeyId, { status });
      }
      clearProviderKeySelection();
      await loadDashboard(token);
      pushNotice('success', 'Bulk provider update', `${selectedCount} keys updated to ${formatStatus(status)}.`);
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'Failed to update selected provider keys';
      pushNotice('error', 'Bulk provider update failed', metricsError);
    } finally {
      actionBusy = false;
    }
  }

  async function handleBulkDeleteProviderKeys() {
    if (!token || !selectedProviderKeyIds.length) {
      return;
    }

    const selectedCount = selectedProviderKeyIds.length;
    actionBusy = true;
    metricsError = '';
    try {
      for (const providerKeyId of [...selectedProviderKeyIds]) {
        await deleteProviderKey(token, providerKeyId);
      }
      clearProviderKeySelection();
      await loadDashboard(token);
      pushNotice('success', 'Bulk provider delete', `${selectedCount} selected provider keys were removed.`);
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'Failed to delete selected provider keys';
      pushNotice('error', 'Bulk provider delete failed', metricsError);
    } finally {
      actionBusy = false;
    }
  }

  function selectProviderKey(providerKey: ProviderKey) {
    selectedProviderKeyId = providerKey.id;
    selectedProviderKeyName = providerKey.name;
    selectedProviderKeyProvider = providerKey.provider;
    selectedProviderKeyDescription = providerKey.description ?? '';
    peekProviderKeyId = null;
    peekResult = '';
    peekError = '';
    peekAdminPassword = '';
  }

  function requestPeekProviderKey(providerKey: ProviderKey) {
    peekProviderKeyId = providerKey.id;
    peekResult = '';
    peekError = '';
    peekAdminPassword = '';
    selectedProviderKeyId = providerKey.id;
    selectedProviderKeyName = providerKey.name;
    selectedProviderKeyProvider = providerKey.provider;
    selectedProviderKeyDescription = providerKey.description ?? '';
  }

  function clearPeekRequest() {
    peekProviderKeyId = null;
    peekAdminPassword = '';
    peekResult = '';
    peekError = '';
  }

  async function handlePeekProviderKey() {
    if (!token || peekProviderKeyId === null || !peekAdminPassword) {
      return;
    }

    actionBusy = true;
    peekError = '';
    try {
      const result = await peekProviderKeyApi(token, peekProviderKeyId, peekAdminPassword);
      peekResult = result.token;
      peekAdminPassword = '';
      pushNotice('info', 'Provider token revealed', 'Use the copy action if you need to move the token elsewhere.');
    } catch (error) {
      peekError = error instanceof Error ? error.message : 'Failed to peek provider key';
      pushNotice('error', 'Provider peek failed', peekError);
    } finally {
      actionBusy = false;
    }
  }

  async function handleCopyPeekResult() {
    if (!peekResult) {
      return;
    }

    await copyToClipboard(peekResult);
  }

  async function handleCopyLastCreatedAppToken() {
    if (!lastCreatedAppToken?.token) {
      return;
    }

    await copyToClipboard(lastCreatedAppToken.token);
  }

  async function handleSaveProviderKey() {
    if (!token || selectedProviderKeyId === null) {
      return;
    }

    actionBusy = true;
    metricsError = '';
    try {
      await updateProviderKey(token, selectedProviderKeyId, {
        name: selectedProviderKeyName,
        provider: selectedProviderKeyProvider,
        description: selectedProviderKeyDescription || null
      });
      await loadDashboard(token);
      pushNotice('success', 'Provider key saved', 'Metadata updated successfully.');
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'Failed to update provider key';
      pushNotice('error', 'Provider key save failed', metricsError);
    } finally {
      actionBusy = false;
    }
  }

  async function handleCreateAppToken() {
    if (!token || !appName) {
      return;
    }

    actionBusy = true;
    metricsError = '';
    try {
      const created = await createAppToken(token, {
        name: appName,
        environment: appEnvironment,
        rpm_limit: appRateLimit ? Number(appRateLimit) : null
      });
      lastCreatedAppToken = created;
      appName = '';
      appRateLimit = '';
      await loadDashboard(token);
      activeSection = 'tokens';
      pushNotice('success', 'App token created', `${created.name} is ready for local apps.`);
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'Failed to create app token';
      pushNotice('error', 'App token creation failed', metricsError);
    } finally {
      actionBusy = false;
    }
  }

  async function handleDeleteAppToken(appTokenId: number) {
    if (!token) {
      return;
    }

    actionBusy = true;
    metricsError = '';
    try {
      await deleteAppToken(token, appTokenId);
      await loadDashboard(token);
      pushNotice('success', 'App token deleted', `App token #${appTokenId} was removed.`);
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'Failed to delete app token';
      pushNotice('error', 'App token delete failed', metricsError);
    } finally {
      actionBusy = false;
    }
  }

  async function handleToggleAppToken(appToken: AppToken) {
    if (!token) {
      return;
    }

    actionBusy = true;
    metricsError = '';
    try {
      await updateAppToken(token, appToken.id, { is_active: !appToken.is_active });
      await loadDashboard(token);
      pushNotice('success', 'App token updated', `${appToken.name} is now ${appToken.is_active ? 'disabled' : 'active'}.`);
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'Failed to update app token';
      pushNotice('error', 'App token update failed', metricsError);
    } finally {
      actionBusy = false;
    }
  }

  async function handleBulkAppTokenActivity(isActive: boolean) {
    if (!token || !selectedAppTokenIds.length) {
      return;
    }

    const selectedCount = selectedAppTokenIds.length;
    actionBusy = true;
    metricsError = '';
    try {
      for (const appTokenId of [...selectedAppTokenIds]) {
        await updateAppToken(token, appTokenId, { is_active: isActive });
      }
      clearAppTokenSelection();
      await loadDashboard(token);
      pushNotice('success', 'Bulk app update', `${selectedCount} app tokens updated.`);
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'Failed to update selected app tokens';
      pushNotice('error', 'Bulk app update failed', metricsError);
    } finally {
      actionBusy = false;
    }
  }

  async function handleBulkDeleteAppTokens() {
    if (!token || !selectedAppTokenIds.length) {
      return;
    }

    const selectedCount = selectedAppTokenIds.length;
    actionBusy = true;
    metricsError = '';
    try {
      for (const appTokenId of [...selectedAppTokenIds]) {
        await deleteAppToken(token, appTokenId);
      }
      clearAppTokenSelection();
      await loadDashboard(token);
      pushNotice('success', 'Bulk app delete', `${selectedCount} selected app tokens were removed.`);
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'Failed to delete selected app tokens';
      pushNotice('error', 'Bulk app delete failed', metricsError);
    } finally {
      actionBusy = false;
    }
  }

  function selectAppToken(appToken: AppToken) {
    selectedAppTokenId = appToken.id;
    selectedAppTokenName = appToken.name;
    selectedAppTokenEnvironment = appToken.environment;
    selectedAppTokenRateLimit = appToken.rpm_limit ? String(appToken.rpm_limit) : '';
    selectedAppTokenIsActive = appToken.is_active;
    selectedAppTokenSecret = null;
  }

  async function copyToClipboard(text: string) {
    if (typeof navigator === 'undefined' || !navigator.clipboard) {
      return;
    }

    await navigator.clipboard.writeText(text);
  }

  async function handleSaveAppToken() {
    if (!token || selectedAppTokenId === null) {
      return;
    }

    actionBusy = true;
    metricsError = '';
    try {
      await updateAppToken(token, selectedAppTokenId, {
        name: selectedAppTokenName,
        environment: selectedAppTokenEnvironment,
        rpm_limit: selectedAppTokenRateLimit ? Number(selectedAppTokenRateLimit) : null,
        is_active: selectedAppTokenIsActive
      });
      await loadDashboard(token);
      pushNotice('success', 'App token saved', 'Metadata updated successfully.');
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'Failed to update app token';
      pushNotice('error', 'App token save failed', metricsError);
    } finally {
      actionBusy = false;
    }
  }

  async function handleCreateModelQueue() {
    if (!token || !queueName) {
      return;
    }

    actionBusy = true;
    metricsError = '';
    try {
      const created = await createModelQueue(token, {
        name: queueName,
        description: queueDescription || null,
        strategy: queueStrategy
      });
      queueName = '';
      queueDescription = '';
      queueStrategy = 'ordered';
      await loadDashboard(token);
      activeSection = 'queues';
      selectQueue(created);
      pushNotice('success', 'Model queue created', `${created.name} is ready.`);
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'Failed to create model queue';
      pushNotice('error', 'Model queue creation failed', metricsError);
    } finally {
      actionBusy = false;
    }
  }

  async function handleSaveModelQueue() {
    if (!token || selectedQueueId === null) {
      return;
    }

    actionBusy = true;
    metricsError = '';
    try {
      await updateModelQueue(token, selectedQueueId, {
        name: queueName,
        description: queueDescription || null,
        strategy: queueStrategy
      });
      await loadDashboard(token);
      pushNotice('success', 'Model queue saved', 'Queue settings updated.');
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'Failed to update model queue';
      pushNotice('error', 'Model queue save failed', metricsError);
    } finally {
      actionBusy = false;
    }
  }

  async function handleDeleteModelQueue(queueId: number) {
    if (!token) {
      return;
    }

    actionBusy = true;
    metricsError = '';
    try {
      await deleteModelQueue(token, queueId);
      if (selectedQueueId === queueId) {
        selectedQueueId = null;
        selectedQueueCandidateId = null;
      }
      await loadDashboard(token);
      pushNotice('success', 'Model queue deleted', `Queue #${queueId} was removed.`);
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'Failed to delete model queue';
      pushNotice('error', 'Model queue delete failed', metricsError);
    } finally {
      actionBusy = false;
    }
  }

  async function handleAddQueueCandidate() {
    if (!token || selectedQueueId === null || !selectedQueueCandidateModelName) {
      return;
    }

    actionBusy = true;
    metricsError = '';
    try {
      await createModelQueueCandidate(token, selectedQueueId, {
        provider: selectedQueueCandidateProvider,
        model_name: selectedQueueCandidateModelName,
        position: Number(selectedQueueCandidatePosition) || 0,
        is_active: selectedQueueCandidateIsActive
      });
      await loadDashboard(token);
      pushNotice('success', 'Queue candidate added', `${selectedQueueCandidateModelName} added to queue.`);
      showQueueCandidateModal = false;
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'Failed to add queue candidate';
      pushNotice('error', 'Queue candidate add failed', metricsError);
    } finally {
      actionBusy = false;
    }
  }

  async function handleSaveQueueCandidate() {
    if (!token || selectedQueueCandidateId === null) {
      return;
    }

    actionBusy = true;
    metricsError = '';
    try {
      await updateModelQueueCandidate(token, selectedQueueCandidateId, {
        provider: selectedQueueCandidateProvider,
        model_name: selectedQueueCandidateModelName,
        position: Number(selectedQueueCandidatePosition) || 0,
        is_active: selectedQueueCandidateIsActive
      });
      await loadDashboard(token);
      pushNotice('success', 'Queue candidate saved', 'Candidate updated successfully.');
      showQueueCandidateModal = false;
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'Failed to update queue candidate';
      pushNotice('error', 'Queue candidate save failed', metricsError);
    } finally {
      actionBusy = false;
    }
  }

  async function handleDeleteQueueCandidate(candidateId: number) {
    if (!token) {
      return;
    }

    actionBusy = true;
    metricsError = '';
    try {
      await deleteModelQueueCandidate(token, candidateId);
      if (selectedQueueCandidateId === candidateId) {
        selectedQueueCandidateId = null;
      }
      await loadDashboard(token);
      pushNotice('success', 'Queue candidate deleted', `Candidate #${candidateId} removed.`);
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'Failed to delete queue candidate';
      pushNotice('error', 'Queue candidate delete failed', metricsError);
    } finally {
      actionBusy = false;
    }
  }

  async function handlePeekAppToken() {
    if (!token || selectedAppTokenId === null) {
      return;
    }

    actionBusy = true;
    metricsError = '';
    try {
      selectedAppTokenSecret = await peekAppTokenApi(token, selectedAppTokenId);
      pushNotice('success', 'App token revealed', `${selectedAppTokenName} token is ready to copy.`);
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'Failed to reveal app token';
      pushNotice('error', 'App token reveal failed', metricsError);
    } finally {
      actionBusy = false;
    }
  }

  async function handleRotateAppToken() {
    if (!token || selectedAppTokenId === null) {
      return;
    }

    actionBusy = true;
    metricsError = '';
    try {
      selectedAppTokenSecret = await rotateAppTokenApi(token, selectedAppTokenId);
      await loadDashboard(token);
      pushNotice('success', 'App token rotated', `${selectedAppTokenName} received a new token.`);
    } catch (error) {
      metricsError = error instanceof Error ? error.message : 'Failed to rotate app token';
      pushNotice('error', 'App token rotation failed', metricsError);
    } finally {
      actionBusy = false;
    }
  }

  async function handleCopySelectedAppTokenSecret() {
    if (!selectedAppTokenSecret?.token) {
      return;
    }

    await copyToClipboard(selectedAppTokenSecret.token);
    pushNotice('success', 'Token copied', `${selectedAppTokenName} token copied to clipboard.`);
  }

  function formatMetric(value: number, fractionDigits = 0) {
    return new Intl.NumberFormat('en-US', {
      maximumFractionDigits: fractionDigits,
      minimumFractionDigits: fractionDigits
    }).format(value);
  }

  function formatDate(value: string) {
    return new Intl.DateTimeFormat('en-US', {
      dateStyle: 'medium',
      timeStyle: 'short',
      timeZone: 'America/Sao_Paulo'
    }).format(new Date(value));
  }

  function formatUsageStatus(log: UsageLog) {
    if (log.status_code >= 200 && log.status_code < 300) {
      return 'Success';
    }
    if (log.status_code === 429) {
      return 'Rate limited';
    }
    if (log.status_code === 404) {
      return 'Model not found';
    }
    if (log.status_code === 400) {
      return 'Invalid request';
    }
    if (log.status_code === 401 || log.status_code === 403) {
      return 'Unauthorized';
    }
    if (log.status_code >= 500) {
      return 'Provider error';
    }
    return `Status ${log.status_code}`;
  }

  function formatUsageError(errorMessage: string | null) {
    if (!errorMessage) {
      return '';
    }

    try {
      const parsed = JSON.parse(errorMessage) as unknown;
      if (typeof parsed === 'string') {
        return parsed;
      }
      if (Array.isArray(parsed)) {
        for (const entry of parsed) {
          if (typeof entry === 'string') {
            return entry;
          }
          if (entry && typeof entry === 'object') {
            const candidate = (entry as { error?: { message?: string } }).error?.message;
            if (candidate) {
              return candidate;
            }
          }
        }
      }
      if (parsed && typeof parsed === 'object') {
        const maybeError = parsed as { error?: { message?: string; status?: string }; detail?: string; message?: string };
        return maybeError.error?.message ?? maybeError.detail ?? maybeError.message ?? 'Upstream error';
      }
    } catch {
      return errorMessage;
    }

    return 'Upstream error';
  }

  function openUsageLog(log: UsageLog) {
    selectedUsageLog = log;
  }

  function closeUsageLog() {
    selectedUsageLog = null;
  }

  function formatStatus(value: ProviderKey['status']) {
    return value.replaceAll('_', ' ').toLowerCase();
  }

  function handleCardKeydown(event: KeyboardEvent, action: () => void) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      action();
    }
  }

  function isProviderKeySelected(providerKeyId: number) {
    return selectedProviderKeyIds.includes(providerKeyId);
  }

  function toggleProviderKeySelection(providerKeyId: number) {
    selectedProviderKeyIds = selectedProviderKeyIds.includes(providerKeyId)
      ? selectedProviderKeyIds.filter((id) => id !== providerKeyId)
      : [...selectedProviderKeyIds, providerKeyId];
  }

  function clearProviderKeySelection() {
    selectedProviderKeyIds = [];
  }

  function selectAllFilteredProviderKeys() {
    selectedProviderKeyIds = filteredProviderKeys.map((providerKey) => providerKey.id);
  }

  function isAppTokenSelected(appTokenId: number) {
    return selectedAppTokenIds.includes(appTokenId);
  }

  function toggleAppTokenSelection(appTokenId: number) {
    selectedAppTokenIds = selectedAppTokenIds.includes(appTokenId)
      ? selectedAppTokenIds.filter((id) => id !== appTokenId)
      : [...selectedAppTokenIds, appTokenId];
  }

  function clearAppTokenSelection() {
    selectedAppTokenIds = [];
  }

  function selectAllFilteredAppTokens() {
    selectedAppTokenIds = filteredAppTokens.map((appToken) => appToken.id);
  }

  function loadUiPreferences(): Partial<UiPreferences> {
    if (typeof localStorage === 'undefined') {
      return {};
    }

    try {
      const raw = localStorage.getItem(UI_PREFERENCES_KEY);
      if (!raw) {
        return {};
      }

      return JSON.parse(raw) as Partial<UiPreferences>;
    } catch {
      return {};
    }
  }

  function saveUiPreferences() {
    if (typeof localStorage === 'undefined' || !isHydrated) {
      return;
    }

    const preferences: UiPreferences = {
      activeSection,
      providerKeyProviderFilter,
      providerKeyStatusFilter,
      providerKeySearch,
      appTokenActiveFilter,
      appTokenSearch,
      usageAppTokenFilter,
      usageProviderKeyFilter,
      usageQueueFilter,
      usageProtocolInFilter,
      usageProtocolOutFilter,
      usageRouteKindFilter,
      usageToolCallingFilter,
      usageLimit,
      usagePage,
      activityFilter,
      activitySearch,
      autoRefreshEnabled
    };
    localStorage.setItem(UI_PREFERENCES_KEY, JSON.stringify(preferences));
  }

  function loadActivityLog(): Notice[] {
    if (typeof localStorage === 'undefined') {
      return [];
    }

    try {
      const raw = localStorage.getItem(UI_ACTIVITY_KEY);
      if (!raw) {
        return [];
      }

      const parsed = JSON.parse(raw) as Notice[];
      return Array.isArray(parsed) ? parsed.slice(0, 12) : [];
    } catch {
      return [];
    }
  }

  function saveActivityLog() {
    if (typeof localStorage === 'undefined' || !isHydrated) {
      return;
    }

    localStorage.setItem(UI_ACTIVITY_KEY, JSON.stringify(activityLog.slice(0, 12)));
  }

  $: if (isHydrated) {
    saveUiPreferences();
  }

  let unsubscribeRefresh: () => void;

  onMount(() => {
    unsubscribeRefresh = refreshTrigger.subscribe(() => {
      if (isHydrated && token) {
        void refreshDashboard();
      }
    });
    const savedPreferences = loadUiPreferences();
    if (savedPreferences.activeSection) {
      activeSection = savedPreferences.activeSection;
    }
    if (savedPreferences.providerKeyProviderFilter !== undefined) {
      providerKeyProviderFilter = savedPreferences.providerKeyProviderFilter ?? '';
    }
    if (savedPreferences.providerKeyStatusFilter !== undefined) {
      providerKeyStatusFilter = savedPreferences.providerKeyStatusFilter ?? '';
    }
    if (savedPreferences.providerKeySearch !== undefined) {
      providerKeySearch = savedPreferences.providerKeySearch ?? '';
    }
    if (savedPreferences.appTokenActiveFilter !== undefined) {
      appTokenActiveFilter = savedPreferences.appTokenActiveFilter ?? '';
    }
    if (savedPreferences.appTokenSearch !== undefined) {
      appTokenSearch = savedPreferences.appTokenSearch ?? '';
    }
    if (savedPreferences.usageAppTokenFilter !== undefined) {
      usageAppTokenFilter = savedPreferences.usageAppTokenFilter ?? '';
    }
    if (savedPreferences.usageProviderKeyFilter !== undefined) {
      usageProviderKeyFilter = savedPreferences.usageProviderKeyFilter ?? '';
    }
    if (savedPreferences.usageQueueFilter !== undefined) {
      usageQueueFilter = savedPreferences.usageQueueFilter ?? '';
    }
    if (savedPreferences.usageProtocolInFilter !== undefined) {
      usageProtocolInFilter = savedPreferences.usageProtocolInFilter ?? '';
    }
    if (savedPreferences.usageProtocolOutFilter !== undefined) {
      usageProtocolOutFilter = savedPreferences.usageProtocolOutFilter ?? '';
    }
    if (savedPreferences.usageRouteKindFilter !== undefined) {
      usageRouteKindFilter = savedPreferences.usageRouteKindFilter ?? '';
    }
    if (savedPreferences.usageToolCallingFilter !== undefined) {
      usageToolCallingFilter = savedPreferences.usageToolCallingFilter ?? '';
    }
    if (savedPreferences.usageLimit !== undefined && Number.isFinite(savedPreferences.usageLimit)) {
      usageLimit = savedPreferences.usageLimit;
    }
    if (savedPreferences.usagePage !== undefined && Number.isFinite(savedPreferences.usagePage)) {
      usagePage = Math.max(1, savedPreferences.usagePage);
    }
    if (savedPreferences.activityFilter) {
      activityFilter = savedPreferences.activityFilter;
    }
    if (savedPreferences.activitySearch !== undefined) {
      activitySearch = savedPreferences.activitySearch ?? '';
    }
    if (savedPreferences.autoRefreshEnabled !== undefined) {
      autoRefreshEnabled = savedPreferences.autoRefreshEnabled;
    }

    activityLog = loadActivityLog();
    noticeSequence = activityLog.reduce((max, entry) => Math.max(max, entry.id), 0);
    themeMode = getStoredThemeMode();
    applyThemeMode(themeMode);

    if (typeof window !== 'undefined' && window.matchMedia) {
      themeMediaQuery = window.matchMedia('(prefers-color-scheme: light)');
      themeMediaQueryHandler = () => {
        if (themeMode === 'system') {
          applyThemeMode('system');
        }
      };
      themeMediaQuery.addEventListener('change', themeMediaQueryHandler);
    }

    isHydrated = true;

    const savedToken = getStoredAdminToken();
    if (!savedToken) {
      void goto('/login');
      return;
    }

    void refreshBackendHealth();

    healthTimer = setInterval(() => {
      void refreshBackendHealth();
    }, 30000);

    refreshTimer = setInterval(() => {
      if (autoRefreshEnabled && token && !loading) {
        void refreshDashboard();
      }
    }, 60000);

    void loadDashboard(savedToken);
  });

  onDestroy(() => {
    if (unsubscribeRefresh) {
      unsubscribeRefresh();
    }
    if (healthTimer) {
      clearInterval(healthTimer);
    }
    if (refreshTimer) {
      clearInterval(refreshTimer);
    }
    if (themeMediaQuery && themeMediaQueryHandler) {
      themeMediaQuery.removeEventListener('change', themeMediaQueryHandler);
    }
  });

  $: if (isHydrated) {
    if (!autoRefreshEnabled && refreshTimer) {
      clearInterval(refreshTimer);
      refreshTimer = null;
    } else if (autoRefreshEnabled && !refreshTimer) {
      refreshTimer = setInterval(() => {
        if (token && !loading) {
          void refreshDashboard();
        }
      }, 60000);
    }
  }
</script>

<svelte:head>
  <title>LLMBridge Control Plane</title>
  <meta
    name="description"
    content="Local LLM gateway dashboard for runtime, keys, tokens, and usage control."
  />
</svelte:head>

  <div class="toast-container" aria-live="polite" aria-atomic="true">
        {#each notices as notice (notice.id)}
          <div class={`toast ${notice.type}`}>
            <div class="toast-content">
              <strong>{notice.title}</strong>
              <p>{notice.detail}</p>
            </div>
            <button type="button" class="toast-close" aria-label="Dismiss notification" on:click={() => notices = notices.filter(n => n.id !== notice.id)}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg>
            </button>
          </div>
        {/each}
      </div>

      {#if activeSection === 'overview'}
        <section class="section-block">
          <div class="section-title">
            <h2>Overview</h2>
            <div class="activity-filters" role="tablist">
              <button type="button" class="ghost" class:active={overviewRange === '1h'} on:click={() => setOverviewRange('1h')}>1h</button>
              <button type="button" class="ghost" class:active={overviewRange === '24h'} on:click={() => setOverviewRange('24h')}>24h</button>
              <button type="button" class="ghost" class:active={overviewRange === '7d'} on:click={() => setOverviewRange('7d')}>7d</button>
              <button type="button" class="ghost" class:active={overviewRange === '30d'} on:click={() => setOverviewRange('30d')}>30d</button>
            </div>
          </div>

          {#if !globalMetrics || globalMetrics.total_requests === 0}
            <div class="smart-empty">
              <BarChart2 size={32} strokeWidth={1.2} color="rgba(255,255,255,0.2)" />
              <strong>No traffic yet</strong>
              <p>Send requests through the gateway to populate usage, latency and quota charts.</p>
            </div>
          {/if}

          <div class="metric-grid">
            <div class="metric-card">
              <span>Total requests</span>
              <strong>{globalMetrics ? formatMetric(globalMetrics.total_requests) : '0'}</strong>
            </div>
            <div class="metric-card">
              <span>Success rate</span>
              <strong>{globalMetrics ? `${formatMetric(globalMetrics.success_rate, 1)}%` : '0%'}</strong>
            </div>
            <div class="metric-card">
              <span>Active keys</span>
              <strong>{globalMetrics ? formatMetric(globalMetrics.active_keys_count) : '0'}</strong>
            </div>
            <div class="metric-card">
              <span>Total tokens</span>
              <strong>{globalMetrics ? formatMetric(globalMetrics.total_tokens_consumed) : '0'}</strong>
            </div>
            <div class="metric-card">
              <span>Avg Latency</span>
              <strong>{globalMetrics?.avg_latency_ms ? `${globalMetrics.avg_latency_ms.toFixed(1)}ms` : '0ms'}</strong>
            </div>
            <div class="metric-card">
              <span>Cooldown keys</span>
              <strong>{globalMetrics ? formatMetric(globalMetrics.cooldown_keys_count) : '0'}</strong>
            </div>
            <div class="metric-card">
              <span>Rotations</span>
              <strong>{globalMetrics ? formatMetric(globalMetrics.total_rotations_triggered) : '0'}</strong>
            </div>
            <div class="metric-card">
              <span>Error rate</span>
              <strong>{globalMetrics?.success_rate ? `${(100 - globalMetrics.success_rate).toFixed(1)}%` : '0%'}</strong>
            </div>
          </div>

          <div class="dashboard-row">
            <div class="dashboard-card wide-card">
              <div class="card-header">
                <div class="card-header-row">
                  <h3>Usage over time</h3>
                </div>
              </div>
              <div class="card-body chart-grid">
                <div class="chart-panel">
                  {#if overviewBuckets.length}
                    <div style="height: 280px; position: relative;">
                      <Line data={masterChartData} options={masterChartOptions} />
                    </div>
                    <div class="chart-axis">
                      <span>{overviewBuckets[0] ? formatOverviewTimeLabel(overviewBuckets[0].bucket_start, overviewRange) : ''}</span>
                      <span>{overviewBuckets[overviewBuckets.length - 1] ? formatOverviewTimeLabel(overviewBuckets[overviewBuckets.length - 1].bucket_end, overviewRange) : ''}</span>
                    </div>
                  {:else}
                    <div class="chart-empty">No historical data yet</div>
                  {/if}
                </div>
                <div class="overview-side-card">
                  <div class="card-header">
                    <div class="card-header-row">
                      <h3>App Requests</h3>
                      <span class="chart-legend accent">{projectMetrics.length} apps</span>
                    </div>
                  </div>
                  <div class="card-body">
                    {#if projectMetrics.length}
                      <div class="chart-stage chart-stage-donut chart-stage-donut-compact">
                        <Doughnut data={appRequestsData} options={biChartOptions} />
                      </div>
                    {:else}
                      <div class="chart-empty compact">No data</div>
                    {/if}
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div class="dashboard-row cols-2 app-chart-row">
            <div class="dashboard-card chart-card app-chart-card app-chart-card-bar">
              <div class="card-header">
                <div class="card-header-row">
                  <h3>App Tokens</h3>
                  <span class="chart-legend accent">{formatMetric(overviewTokensTotal)} total</span>
                </div>
              </div>
              <div class="card-body">
                {#if projectMetrics.length}
                  <div class="chart-stage chart-stage-bar chart-stage-bar-large">
                    <Bar data={appTokensData} options={appBarChartOptions} />
                  </div>
                {:else}
                  <div class="chart-empty compact">No data</div>
                {/if}
              </div>
            </div>

            <div class="dashboard-card chart-card app-chart-card app-chart-card-bar">
              <div class="card-header">
                <div class="card-header-row">
                  <h3>App Latency</h3>
                  <span class="chart-legend accent">{overviewLatencyAverage ? `${overviewLatencyAverage.toFixed(1)} ms` : '0 ms'}</span>
                </div>
              </div>
              <div class="card-body">
                {#if projectMetrics.length}
                  <div class="chart-stage chart-stage-bar chart-stage-bar-large">
                    <Bar data={appLatencyData} options={appBarChartOptions} />
                  </div>
                {:else}
                  <div class="chart-empty compact">No data</div>
                {/if}
              </div>
            </div>
          </div>

          <div class="dashboard-row cols-2">
            <div class="dashboard-card">
              <div class="card-header">
                <h3>Token Quota</h3>
              </div>
              <div class="card-body">
                {#if !globalMetrics || globalMetrics.total_requests === 0}
                  <div style="padding: 1rem 0; color: var(--muted); font-size: 0.85rem; font-style: italic; text-align: center;">
                    No quotas configured or active usage.
                  </div>
                {:else}
                  <div style="padding: 1rem 0; color: var(--muted); font-size: 0.85rem; font-style: italic; text-align: center;">
                    Global quota tracking pending backend update
                  </div>
                {/if}
              </div>
            </div>
            <div class="dashboard-card">
              <div class="card-header">
                <h3>Provider Status</h3>
              </div>
              <div class="card-body">
                {#if !providerKeys || providerKeys.length === 0}
                  <div style="padding: 1rem 0; color: var(--muted); font-size: 0.85rem; font-style: italic; text-align: center;">
                    No provider keys configured.
                  </div>
                {:else}
                  <div class="provider-list">
                    {#each Array.from(new Set(providerKeys.map(k => k.provider))) as provider}
                      <div class="provider-row">
                        <span class="prov-name">{provider}</span>
                        <span class="prov-status ok">{providerKeys.filter(k => k.provider === provider && k.status === 'ACTIVE').length} active</span>
                      </div>
                    {/each}
                  </div>
                {/if}
              </div>
            </div>
          </div>

          <div class="section-title" style="margin-top: 0.5rem;">
            <h2>Recent Activity</h2>
            <div class="section-toolbar compact">
              <label class="activity-search">
                <input bind:value={activitySearch} type="text" placeholder="Search logs..." />
              </label>
              <div class="activity-filters" role="tablist">
                <button type="button" class:active={activityFilter === 'all'} class="ghost" on:click={() => setActivityFilter('all')}>All</button>
                <button type="button" class:active={activityFilter === 'success'} class="ghost" on:click={() => setActivityFilter('success')}>Success</button>
                <button type="button" class:active={activityFilter === 'error'} class="ghost" on:click={() => setActivityFilter('error')}>Error</button>
              </div>
              <button type="button" class="ghost" on:click={clearActivityLog} disabled={!activityLog.length}>Clear</button>
            </div>
          </div>

          {#if groupedActivityLog.length}
            <div class="activity-list">
              {#each groupedActivityLog as group}
                <div class="activity-group">
                  <div class="activity-group-label">{group.label}</div>
                  <div class="activity-group-items">
                    {#each group.items as activity}
                      <div class={`activity-item ${activity.type}`}>
                        <span class="activity-dot" aria-hidden="true"></span>
                        <div>
                          <div class="activity-topline">
                            <strong>{activity.title}</strong>
                            <span class={`activity-pill ${activity.type}`}>{activity.type}</span>
                          </div>
                          <p>{activity.detail}</p>
                        </div>
                        <time>{new Intl.DateTimeFormat('en-US', { timeStyle: 'short' }).format(new Date(activity.at))}</time>
                      </div>
                    {/each}
                  </div>
                </div>
              {/each}
            </div>
          {:else}
            <p class="muted">
              {#if activitySearch}
                No timeline entries match your search.
              {:else}
                No recent activity.
              {/if}
            </p>
          {/if}
        </section>
      {/if}

      {#if activeSection === 'keys'}
        <section class="section-block">
        <div class="section-shell">
          <div class="section-column">
            <div class="section-toolbar">
              <label class="activity-search">
                <input bind:value={providerKeySearch} type="text" placeholder="Search by name or provider" />
              </label>
              <div class="activity-filters">
                <select bind:value={providerKeyProviderFilter} on:change={handleApplyFilters} class="ghost" style="border:0; height:100%; border-radius:0;">
                  <option value="">all providers</option>
                  <option value="openai">openai</option>
                  <option value="google">google</option>
                  <option value="openrouter">openrouter</option>
                </select>
                <select bind:value={providerKeyStatusFilter} on:change={handleApplyFilters} class="ghost" style="border:0; height:100%; border-radius:0; border-left: 1px solid var(--border);">
                  <option value="">all statuses</option>
                  <option value="ACTIVE">active</option>
                  <option value="COOLDOWN">cooldown</option>
                  <option value="INVALID">invalid</option>
                  <option value="SUSPENDED_BILLING">suspended billing</option>
                </select>
              </div>
              <button type="button" on:click={() => (showProviderKeyModal = true)} style="margin-left: auto;">
                Add provider key
              </button>
            </div>

            {#if showProviderKeyModal}
              <div class="modal-backdrop" on:click={() => (showProviderKeyModal = false)} on:keydown={(e) => e.key === 'Escape' && (showProviderKeyModal = false)} tabindex="0" role="button">
                <div class="modal-content" on:click|stopPropagation on:keydown|stopPropagation tabindex="-1" role="dialog" aria-modal="true">
                  <div class="modal-header">
                    <h3>Add Provider Key</h3>
                    <button type="button" class="ghost" on:click={() => (showProviderKeyModal = false)}>Close</button>
                  </div>
                  <div class="modal-body">
                    <div class="form-grid">
                      <label>
                        Name
                        <input bind:value={providerName} type="text" placeholder="Gemini reserve key" />
                      </label>
                      <label>
                        Provider
                        <select bind:value={providerType}>
                          <option value="openai">openai</option>
                          <option value="google">google</option>
                          <option value="openrouter">openrouter</option>
                        </select>
                      </label>
                      <label class="wide">
                        Description
                        <input bind:value={providerDescription} type="text" placeholder="Optional note" />
                      </label>
                      <label class="wide">
                        Secret token
                        <input bind:value={providerSecret} type="password" placeholder="Paste provider token" />
                      </label>
                    </div>
                  </div>
                  <div class="modal-footer">
                    <button type="button" class="ghost" on:click={() => (showProviderKeyModal = false)}>Cancel</button>
                    <button type="button" class="primary" on:click={() => { handleCreateProviderKey(); showProviderKeyModal = false; }} disabled={actionBusy}>
                      Save key
                    </button>
                  </div>
                </div>
              </div>
            {/if}

            <div class="bulk-bar">
              <div class="bulk-summary">
                <strong>{selectedProviderKeyIds.length}</strong>
                <span>selected</span>
              </div>
              <div class="bulk-actions">
                <button type="button" on:click={selectAllFilteredProviderKeys} disabled={!filteredProviderKeys.length}>
                  Select all
                </button>
                <button type="button" on:click={clearProviderKeySelection} disabled={!selectedProviderKeyIds.length}>
                  Clear
                </button>
                <button type="button" on:click={() => handleBulkProviderKeyStatus('COOLDOWN')} disabled={actionBusy || !selectedProviderKeyIds.length}>
                  Bulk cooldown
                </button>
                <button type="button" on:click={() => handleBulkProviderKeyStatus('ACTIVE')} disabled={actionBusy || !selectedProviderKeyIds.length}>
                  Bulk reactivate
                </button>
                <button type="button" class="btn-danger" on:click={handleBulkDeleteProviderKeys} disabled={actionBusy || !selectedProviderKeyIds.length}>
                  Bulk delete
                </button>
              </div>
            </div>

            <div class="control-table">
              <div class="control-table-head grid-provider-keys">
                <div class="control-table-cell"></div>
                <div class="control-table-cell">Key Name</div>
                <div class="control-table-cell">Provider</div>
                <div class="control-table-cell">Status</div>
                <div class="control-table-cell">Failures</div>
                <div class="control-table-cell actions">Actions</div>
              </div>

              {#each filteredProviderKeys as providerKey}
                <div class="control-table-row grid-provider-keys">
                  <div class="control-table-cell">
                    <label class="select-check" style="margin: 0; display: inline-flex; align-items: center;">
                      <input
                        type="checkbox"
                        checked={isProviderKeySelected(providerKey.id)}
                        on:change={() => toggleProviderKeySelection(providerKey.id)}
                      />
                    </label>
                  </div>
                  <div class="control-table-cell">
                    <strong>{providerKey.name}</strong>
                  </div>
                  <div class="control-table-cell">
                    <span style="text-transform: capitalize;">{providerKey.provider}</span>
                  </div>
                  <div class="control-table-cell">
                    <span class="badge {providerKey.status === 'ACTIVE' ? 'badge-good' : providerKey.status === 'INVALID' ? 'badge-bad' : 'badge-warn'}">
                      {formatStatus(providerKey.status)}
                    </span>
                  </div>
                  <div class="control-table-cell">
                    {providerKey.failure_count}
                  </div>
                  <div class="control-table-cell actions">
                    <button type="button" class="ghost icon-only" title="Open overview" aria-label={`Open overview for ${providerKey.name}`} on:click|stopPropagation={() => openProviderOverview(providerKey)} disabled={actionBusy}>
                      <BarChart2 size={16} />
                    </button>
                    <button type="button" class="ghost icon-only" title={`Edit ${providerKey.name}`} aria-label={`Edit ${providerKey.name}`} on:click|stopPropagation={() => selectProviderKey(providerKey)} disabled={actionBusy}>
                      <Pencil size={15} />
                    </button>
                    <button type="button" class="btn-danger icon-only" title={`Delete ${providerKey.name}`} aria-label={`Delete ${providerKey.name}`} on:click|stopPropagation={() => handleDeleteProviderKey(providerKey.id)} disabled={actionBusy}>
                      <Trash2 size={15} />
                    </button>
                  </div>
                </div>
              {/each}
              {#if !filteredProviderKeys.length}
                <p class="muted" style="padding: 1rem; text-align: center; margin: 0;">No provider keys yet.</p>
              {/if}
            </div>
                     {#if selectedProviderKeyId !== null}
              <div class="modal-backdrop" on:click={() => (selectedProviderKeyId = null)} on:keydown={(e) => e.key === 'Escape' && (selectedProviderKeyId = null)} tabindex="0" role="button">
                <div class="modal-content" on:click|stopPropagation on:keydown|stopPropagation tabindex="-1" role="dialog" aria-modal="true">
                  <div class="modal-header">
                    <h3>Edit Provider Key</h3>
                    <button type="button" class="ghost" on:click={() => (selectedProviderKeyId = null)}>Close</button>
                  </div>
                  <div class="modal-body">
                    {#if selectedProviderKey}
                      <div class="modal-stats">
                        <div class="modal-stat">
                          <span>Provider</span>
                          <strong>{selectedProviderKey.provider}</strong>
                        </div>
                        <div class="modal-stat">
                          <span>Status</span>
                          <strong>{formatStatus(selectedProviderKey.status)}</strong>
                        </div>
                        <div class="modal-stat">
                          <span>Failures</span>
                          <strong>{formatMetric(selectedProviderKey.failure_count)}</strong>
                        </div>
                        <div class="modal-stat">
                          <span>Blocked</span>
                          <strong>{selectedProviderKey.blocked_until ? formatDate(selectedProviderKey.blocked_until) : 'No'}</strong>
                        </div>
                        <div class="modal-stat" style="flex: 1 1 100%;">
                          <span>Token</span>
                          <code style="background: transparent; border: 0; padding: 0;">{selectedProviderKey.masked_token}</code>
                        </div>
                      </div>
                      <div class="form-grid" style="margin-top: 1.5rem;">
                        <label>
                          Name
                          <input bind:value={selectedProviderKeyName} type="text" />
                        </label>
                        <label>
                          Provider
                          <select bind:value={selectedProviderKeyProvider}>
                            <option value="openai">openai</option>
                            <option value="google">google</option>
                            <option value="openrouter">openrouter</option>
                          </select>
                        </label>
                        <label class="wide">
                          Description
                          <input bind:value={selectedProviderKeyDescription} type="text" />
                        </label>
                      </div>
                      <div class="modal-section-actions">
                        <span>Key Operations</span>
                        <div class="action-buttons-group">
                          <button type="button" class="ghost" on:click={() => requestPeekProviderKey(selectedProviderKey)} disabled={actionBusy}>
                            Peek Secret
                          </button>
                          {#if selectedProviderKey.status !== 'COOLDOWN'}
                            <button type="button" class="ghost" on:click={() => handleSetProviderKeyStatus(selectedProviderKey, 'COOLDOWN')} disabled={actionBusy}>
                              Cooldown
                            </button>
                          {/if}
                          {#if selectedProviderKey.status !== 'INVALID'}
                            <button type="button" class="ghost" on:click={() => handleSetProviderKeyStatus(selectedProviderKey, 'INVALID')} disabled={actionBusy}>
                              Invalidate
                            </button>
                          {/if}
                          {#if selectedProviderKey.status !== 'SUSPENDED_BILLING'}
                            <button type="button" class="ghost" on:click={() => handleSetProviderKeyStatus(selectedProviderKey, 'SUSPENDED_BILLING')} disabled={actionBusy}>
                              Suspend Billing
                            </button>
                          {/if}
                          {#if selectedProviderKey.status !== 'ACTIVE'}
                            <button type="button" class="ghost" on:click={() => handleSetProviderKeyStatus(selectedProviderKey, 'ACTIVE')} disabled={actionBusy}>
                              Reactivate
                            </button>
                          {/if}
                        </div>
                      </div>
                    {/if}
                  </div>
                  <div class="modal-footer">
                    <button type="button" class="ghost" on:click={() => (selectedProviderKeyId = null)}>Cancel</button>
                    <button type="button" on:click={() => { handleSaveProviderKey(); selectedProviderKeyId = null; }} disabled={actionBusy}>Save changes</button>
                  </div>
                </div>
              </div>
            {/if}
          </div>

          <div class="section-aside">
            {#if peekProviderKeyId !== null}
              <div class="modal-backdrop" on:click={clearPeekRequest} on:keydown={(e) => e.key === 'Escape' && clearPeekRequest()} tabindex="0" role="button">
                <div class="modal-content" on:click|stopPropagation on:keydown|stopPropagation tabindex="-1" role="dialog" aria-modal="true" style="max-width: 400px;">
                  <div class="modal-header">
                    <h3>Peek Secret Token</h3>
                    <button type="button" class="ghost" on:click={clearPeekRequest}>Close</button>
                  </div>
                  <div class="modal-body">
                    <p style="margin: 0 0 1.25rem 0; padding: 0; font-size: 0.85rem; color: var(--muted); line-height: 1.4;">Enter your admin password to reveal the secret token for this provider key.</p>
                    <div class="form-grid">
                      <label class="wide">
                        Admin password
                        <input bind:value={peekAdminPassword} type="password" placeholder="Re-enter admin password" />
                      </label>
                    </div>
                    <!-- Inline error removed, toast system handles this -->
                    {#if peekResult}
                      <div class="notice success" style="margin-top: 1rem; word-break: break-all;">
                        <strong>Token revealed:</strong>
                        <br />
                        <code>{peekResult}</code>
                        <div style="margin-top: 0.75rem;">
                          <button type="button" class="ghost" on:click={handleCopyPeekResult}>
                            Copy token
                          </button>
                        </div>
                      </div>
                    {/if}
                  </div>
                  <div class="modal-footer">
                    <button type="button" class="ghost" on:click={clearPeekRequest}>Cancel</button>
                    <button type="button" on:click={handlePeekProviderKey} disabled={actionBusy || !peekAdminPassword}>
                      Reveal token
                    </button>
                  </div>
                </div>
              </div>
            {/if}
          </div>
        </div>
        </section>
      {/if}

      {#if activeSection === 'tokens'}
        <section class="section-block">
        <div class="section-shell">
          <div class="section-column">
            <div class="section-toolbar">
              <label class="activity-search">
                <input bind:value={appTokenSearch} type="text" placeholder="Search by name or environment" />
              </label>
              <div class="activity-filters">
                <select
                  bind:value={appTokenActiveFilter}
                  on:change={handleApplyFilters}
                  class="ghost" style="border:0; height:100%; border-radius:0;"
                >
                  <option value="">all tokens</option>
                  <option value="true">active</option>
                  <option value="false">disabled</option>
                </select>
              </div>
              <button type="button" on:click={() => (showAppTokenModal = true)} style="margin-left: auto;">
                Create app token
              </button>
            </div>

            {#if showAppTokenModal}
              <div class="modal-backdrop" on:click={() => (showAppTokenModal = false)} on:keydown={(e) => e.key === 'Escape' && (showAppTokenModal = false)} tabindex="0" role="button">
                <div class="modal-content" on:click|stopPropagation on:keydown|stopPropagation tabindex="-1" role="dialog" aria-modal="true">
                  <div class="modal-header">
                    <h3>Create App Token</h3>
                    <button type="button" class="ghost" on:click={() => (showAppTokenModal = false)}>Close</button>
                  </div>
                  <div class="modal-body">
                    <div class="form-grid">
                      <label>
                        Name
                        <input bind:value={appName} type="text" placeholder="Chatbot support" />
                      </label>
                      <label>
                        Environment
                        <select bind:value={appEnvironment}>
                          <option value="development">development</option>
                          <option value="staging">staging</option>
                          <option value="production">production</option>
                        </select>
                      </label>
                      <label class="wide">
                        RPM limit
                        <input bind:value={appRateLimit} type="number" min="1" placeholder="Optional limit" />
                      </label>
                    </div>
                  </div>
                  <div class="modal-footer">
                    <button type="button" class="ghost" on:click={() => (showAppTokenModal = false)}>Cancel</button>
                    <button type="button" class="primary" on:click={() => { handleCreateAppToken(); showAppTokenModal = false; }} disabled={actionBusy}>
                      Create token
                    </button>
                  </div>
                </div>
              </div>
            {/if}

            {#if lastCreatedAppToken}
              <div class="created-token">
                <div class="created-token-head">
                  <div>
                    <span>Created token</span>
                    <strong>{lastCreatedAppToken.name}</strong>
                  </div>
                  <button type="button" class="ghost" on:click={() => (lastCreatedAppToken = null)}>
                    Dismiss
                  </button>
                </div>
                <div class="created-token-body">
                  <code>{lastCreatedAppToken.token}</code>
                  <button type="button" on:click={handleCopyLastCreatedAppToken}>
                    Copy token
                  </button>
                </div>
              </div>
            {/if}

            <div class="bulk-bar">
              <div class="bulk-summary">
                <strong>{selectedAppTokenIds.length}</strong>
                <span>selected</span>
              </div>
              <div class="bulk-actions">
                <button type="button" on:click={selectAllFilteredAppTokens} disabled={!filteredAppTokens.length}>
                  Select all
                </button>
                <button type="button" on:click={clearAppTokenSelection} disabled={!selectedAppTokenIds.length}>
                  Clear
                </button>
                <button type="button" on:click={() => handleBulkAppTokenActivity(false)} disabled={actionBusy || !selectedAppTokenIds.length}>
                  Bulk disable
                </button>
                <button type="button" on:click={() => handleBulkAppTokenActivity(true)} disabled={actionBusy || !selectedAppTokenIds.length}>
                  Bulk enable
                </button>
                <button type="button" class="btn-danger" on:click={handleBulkDeleteAppTokens} disabled={actionBusy || !selectedAppTokenIds.length}>
                  Bulk delete
                </button>
              </div>
            </div>

            <div class="control-table">
              <div class="control-table-head grid-app-tokens">
                <div class="control-table-cell"></div>
                <div class="control-table-cell">Token Name</div>
                <div class="control-table-cell">Environment</div>
                <div class="control-table-cell">Status</div>
                <div class="control-table-cell">Rate Limit</div>
                <div class="control-table-cell actions">Actions</div>
              </div>

              {#each filteredAppTokens as appToken}
                <div class="control-table-row grid-app-tokens">
                  <div class="control-table-cell">
                    <label class="select-check" style="margin: 0; display: inline-flex; align-items: center;">
                      <input
                        type="checkbox"
                        checked={isAppTokenSelected(appToken.id)}
                        on:change={() => toggleAppTokenSelection(appToken.id)}
                      />
                    </label>
                  </div>
                  <div class="control-table-cell">
                    <strong>{appToken.name}</strong>
                  </div>
                  <div class="control-table-cell">
                    <span style="text-transform: capitalize;">{appToken.environment}</span>
                  </div>
                  <div class="control-table-cell">
                    <span class="badge {appToken.is_active ? 'badge-good' : 'badge-warn'}">
                      {appToken.is_active ? 'active' : 'disabled'}
                    </span>
                  </div>
                  <div class="control-table-cell">
                    {appToken.rpm_limit ? `${appToken.rpm_limit} rpm` : 'No limit'}
                  </div>
                  <div class="control-table-cell actions">
                    <button type="button" class="ghost icon-only" title="Open overview" aria-label={`Open overview for ${appToken.name}`} on:click|stopPropagation={() => openAppTokenOverview(appToken)} disabled={actionBusy}>
                      <BarChart2 size={16} />
                    </button>
                    <button type="button" class="ghost icon-only" title={`Edit ${appToken.name}`} aria-label={`Edit ${appToken.name}`} on:click|stopPropagation={() => selectAppToken(appToken)} disabled={actionBusy}>
                      <Pencil size={15} />
                    </button>
                    <button
                      type="button"
                      class="row-switch"
                      class:on={appToken.is_active}
                      on:click|stopPropagation={() => handleToggleAppToken(appToken)}
                      title={appToken.is_active ? `Disable ${appToken.name}` : `Enable ${appToken.name}`}
                      aria-label={appToken.is_active ? `Disable ${appToken.name}` : `Enable ${appToken.name}`}
                      aria-pressed={appToken.is_active}
                      disabled={actionBusy}
                    >
                      <span class="row-switch-track">
                        <span class="row-switch-thumb"></span>
                      </span>
                    </button>
                    <button type="button" class="btn-danger icon-only" title={`Delete ${appToken.name}`} aria-label={`Delete ${appToken.name}`} on:click={() => handleDeleteAppToken(appToken.id)} disabled={actionBusy}>
                      <Trash2 size={15} />
                    </button>
                  </div>
                </div>
              {/each}
              {#if !filteredAppTokens.length}
                <p class="muted" style="padding: 1rem; text-align: center; margin: 0;">No app tokens yet.</p>
              {/if}
            </div>
          </div>

            {#if selectedAppTokenId !== null}
              <div class="modal-backdrop" on:click={() => { selectedAppTokenId = null; selectedAppTokenSecret = null; }} on:keydown={(e) => e.key === 'Escape' && ((selectedAppTokenId = null), (selectedAppTokenSecret = null))} tabindex="0" role="button">
                <div class="modal-content" on:click|stopPropagation on:keydown|stopPropagation tabindex="-1" role="dialog" aria-modal="true">
                  <div class="modal-header">
                    <h3>Edit App Token</h3>
                    <button type="button" class="ghost" on:click={() => { selectedAppTokenId = null; selectedAppTokenSecret = null; }}>Close</button>
                  </div>
                  <div class="modal-body">
                    {#if selectedAppToken}
                      <div class="modal-stats">
                        <div class="modal-stat">
                          <span>Environment</span>
                          <strong>{selectedAppToken.environment}</strong>
                        </div>
                        <div class="modal-stat">
                          <span>Activity</span>
                          <strong>{selectedAppToken.is_active ? 'Active' : 'Disabled'}</strong>
                        </div>
                        <div class="modal-stat">
                          <span>Rate limit</span>
                          <strong>{selectedAppToken.rpm_limit ? `${selectedAppToken.rpm_limit} rpm` : 'No limit'}</strong>
                        </div>
                        <div class="modal-stat">
                          <span>Created</span>
                          <strong>{formatDate(selectedAppToken.created_at)}</strong>
                        </div>
                        <div class="modal-stat" style="flex: 1 1 100%;">
                          <span>Token</span>
                          <code style="background: transparent; border: 0; padding: 0;">{selectedAppToken.masked_token}</code>
                        </div>
                      </div>
                    {/if}
                    <div class="modal-actions" style="margin-top: 1rem;">
                      <button type="button" class="ghost" on:click={handlePeekAppToken} disabled={actionBusy}>
                        Reveal token
                      </button>
                      <button type="button" class="ghost" on:click={handleRotateAppToken} disabled={actionBusy}>
                        Rotate token
                      </button>
                    </div>
                    <div class="form-grid" style="margin-top: 1.5rem;">
                      <label>
                        Name
                        <input bind:value={selectedAppTokenName} type="text" />
                      </label>
                      <label>
                        Environment
                        <select bind:value={selectedAppTokenEnvironment}>
                          <option value="development">development</option>
                          <option value="staging">staging</option>
                          <option value="production">production</option>
                        </select>
                      </label>
                      <label class="wide">
                        RPM limit
                        <input bind:value={selectedAppTokenRateLimit} type="number" min="1" placeholder="Optional limit" />
                      </label>
                      <label class="wide checkbox-row">
                        <input bind:checked={selectedAppTokenIsActive} type="checkbox" />
                        <span>Token is active</span>
                      </label>
                    </div>
                  </div>
                  <div class="modal-footer">
                    <button type="button" class="ghost" on:click={() => { selectedAppTokenId = null; selectedAppTokenSecret = null; }}>Cancel</button>
                    <button type="button" on:click={() => { handleSaveAppToken(); selectedAppTokenId = null; selectedAppTokenSecret = null; }} disabled={actionBusy}>Save changes</button>
                  </div>
                </div>
              </div>
            {/if}

            {#if selectedAppTokenSecret}
              <div class="modal-backdrop" on:click={() => (selectedAppTokenSecret = null)} on:keydown={(e) => e.key === 'Escape' && (selectedAppTokenSecret = null)} tabindex="0" role="button">
                <div class="modal-content" on:click|stopPropagation on:keydown|stopPropagation tabindex="-1" role="dialog" aria-modal="true">
                  <div class="modal-header">
                    <h3>App Token</h3>
                    <button type="button" class="ghost" on:click={() => (selectedAppTokenSecret = null)}>Close</button>
                  </div>
                  <div class="modal-body">
                    <div class="token-reveal-flat">
                      <strong>{selectedAppTokenName}</strong>
                      <div class="token-reveal-row">
                        <code>{selectedAppTokenSecret.token}</code>
                        <button
                          type="button"
                          class="ghost icon-only"
                          on:click={handleCopySelectedAppTokenSecret}
                          aria-label="Copy token"
                          title="Copy token"
                        >
                          <Copy size={15} />
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            {/if}
        </div>
        </section>
      {/if}

      {#if activeSection === 'queues'}
        <section class="section-block">
          <div class="section-toolbar">
            <label class="activity-search">
              <input bind:value={queueSearch} type="text" placeholder="Search queues" />
            </label>
            <button type="button" on:click={openCreateModelQueueModal} style="margin-left: auto;">
              Add queue
            </button>
          </div>

          {#if showModelQueueModal}
            <div class="modal-backdrop" on:click={() => { showModelQueueModal = false; showQueueCandidateModal = false; }} on:keydown={(e) => e.key === 'Escape' && ((showModelQueueModal = false), (showQueueCandidateModal = false))} tabindex="0" role="button">
              <div class="modal-content" style={queueModalMode === 'edit' ? 'max-width: 800px; max-height: 90vh; overflow-y: auto;' : ''} on:click|stopPropagation on:keydown|stopPropagation tabindex="-1" role="dialog" aria-modal="true">
                <div class="modal-header">
                  <h3>{queueModalMode === 'create' ? 'Add Queue' : 'Edit Queue'}</h3>
                  <button type="button" class="ghost" on:click={() => { showModelQueueModal = false; showQueueCandidateModal = false; }}>Close</button>
                </div>
                <div class="modal-body">
                  <div class="form-grid">
                    <label>
                      Name
                      <input bind:value={queueName} type="text" placeholder="production" />
                    </label>
                    <label>
                      Strategy
                      <select bind:value={queueStrategy}>
                        <option value="ordered">ordered</option>
                        <option value="smart">smart</option>
                        <option value="latency">latency</option>
                      </select>
                    </label>
                    <label class="wide">
                      Description
                      <input bind:value={queueDescription} type="text" placeholder="Optional notes" />
                    </label>
                  </div>

                  {#if queueModalMode === 'edit' && selectedQueue}
                    <div class="section-title" style="margin-top: 2rem; display: flex; align-items: center; justify-content: space-between;">
                      <h2>Candidates</h2>
                      <button type="button" class="ghost" on:click={() => {
                        selectedQueueCandidateId = null;
                        selectedQueueCandidateProvider = 'google';
                        selectedQueueCandidateModelName = '';
                        selectedQueueCandidatePosition = selectedQueue?.candidates.length ?? 0;
                        selectedQueueCandidateIsActive = true;
                        showQueueCandidateModal = true;
                      }}>
                        Add candidate
                      </button>
                    </div>

                    <div class="control-table">
                      <div class="control-table-head grid-queue-candidates">
                        <div class="control-table-cell">Model Name</div>
                        <div class="control-table-cell">Position</div>
                        <div class="control-table-cell">Status</div>
                        <div class="control-table-cell">Score</div>
                        <div class="control-table-cell">Errors</div>
                        <div class="control-table-cell">Latency</div>
                        <div class="control-table-cell actions">Actions</div>
                      </div>

                      {#each selectedQueue.candidates as candidate}
                        <div class="control-table-row grid-queue-candidates">
                          <div class="control-table-cell">
                            <strong>{candidate.provider}/{candidate.model_name}</strong>
                          </div>
                          <div class="control-table-cell">
                            {candidate.position}
                          </div>
                          <div class="control-table-cell">
                            <span class="badge {candidate.is_active ? 'badge-good' : 'badge-warn'}">
                              {candidate.is_active ? 'active' : 'disabled'}
                            </span>
                          </div>
                          <div class="control-table-cell">
                            {candidate.score.toFixed(2)}
                          </div>
                          <div class="control-table-cell">
                            {candidate.failure_count}
                          </div>
                          <div class="control-table-cell">
                            {candidate.avg_latency_ms ? `${candidate.avg_latency_ms.toFixed(1)}ms` : '0ms'}
                          </div>
                          <div class="control-table-cell actions">
                            <button type="button" class="ghost icon-only" title={`Edit ${candidate.provider}/${candidate.model_name}`} aria-label={`Edit ${candidate.provider}/${candidate.model_name}`} on:click|stopPropagation={() => selectQueueCandidate(candidate)} disabled={actionBusy}>
                              <Pencil size={15} />
                            </button>
                            <button type="button" class="btn-danger icon-only" title={`Delete ${candidate.provider}/${candidate.model_name}`} aria-label={`Delete ${candidate.provider}/${candidate.model_name}`} on:click|stopPropagation={() => handleDeleteQueueCandidate(candidate.id)} disabled={actionBusy}>
                              <Trash2 size={15} />
                            </button>
                          </div>
                        </div>
                      {/each}
                      {#if !selectedQueue.candidates.length}
                        <p class="muted" style="padding: 1rem; text-align: center; margin: 0;">No candidates yet.</p>
                      {/if}
                    </div>
                  {/if}
                </div>
                <div class="modal-footer">
                  <button type="button" class="ghost" on:click={() => { showModelQueueModal = false; showQueueCandidateModal = false; }}>Cancel</button>
                  <button
                    type="button"
                    class="primary"
                    on:click={queueModalMode === 'create'
                      ? () => { handleCreateModelQueue(); showModelQueueModal = false; showQueueCandidateModal = false; }
                      : () => { handleSaveModelQueue(); showModelQueueModal = false; showQueueCandidateModal = false; }}
                    disabled={actionBusy}
                  >
                    {queueModalMode === 'create' ? 'Create queue' : 'Save queue'}
                  </button>
                </div>
              </div>
            </div>
          {/if}

          {#if showQueueCandidateModal}
            <div class="modal-backdrop-nested" on:click={() => (showQueueCandidateModal = false)} on:keydown={(e) => e.key === 'Escape' && (showQueueCandidateModal = false)} tabindex="0" role="button">
              <div class="modal-content-nested" on:click|stopPropagation on:keydown|stopPropagation tabindex="-1" role="dialog" aria-modal="true">
                <div class="modal-header">
                  <h3>{selectedQueueCandidateId === null ? 'Add Candidate' : 'Edit Candidate'}</h3>
                  <button type="button" class="ghost" on:click={() => (showQueueCandidateModal = false)}>Close</button>
                </div>
                <div class="modal-body">
                  <div class="form-grid">
                    <label>
                      Provider
                      <select bind:value={selectedQueueCandidateProvider}>
                        <option value="google">google</option>
                        <option value="openai">openai</option>
                        <option value="openrouter">openrouter</option>
                      </select>
                    </label>
                    <label>
                      Model Name
                      <input bind:value={selectedQueueCandidateModelName} type="text" placeholder="gemini-3-flash-preview" />
                    </label>
                    <label>
                      Position
                      <input bind:value={selectedQueueCandidatePosition} type="number" min="0" />
                    </label>
                    <label class="wide checkbox-row">
                      <input bind:checked={selectedQueueCandidateIsActive} type="checkbox" />
                      <span>Candidate is active</span>
                    </label>
                  </div>
                </div>
                <div class="modal-footer">
                  <button type="button" class="ghost" on:click={() => (showQueueCandidateModal = false)}>Cancel</button>
                  <button type="button" class="primary" on:click={selectedQueueCandidateId === null ? handleAddQueueCandidate : handleSaveQueueCandidate} disabled={actionBusy}>
                    {selectedQueueCandidateId === null ? 'Add candidate' : 'Save candidate'}
                  </button>
                </div>
              </div>
            </div>
          {/if}

          <div class="control-table">
            <div class="control-table-head grid-model-queues">
              <div class="control-table-cell">Queue Name</div>
              <div class="control-table-cell">Strategy</div>
              <div class="control-table-cell">Status</div>
              <div class="control-table-cell">Candidates</div>
              <div class="control-table-cell actions">Actions</div>
            </div>

            {#each filteredModelQueues as queue}
              <div class="control-table-row grid-model-queues">
                <div class="control-table-cell">
                  <strong>{queue.name}</strong>
                </div>
                <div class="control-table-cell">
                  <span style="text-transform: capitalize;">{queue.strategy}</span>
                </div>
                <div class="control-table-cell">
                  <span class="badge {queue.is_active ? 'badge-good' : 'badge-warn'}">
                    {queue.is_active ? 'active' : 'disabled'}
                  </span>
                </div>
                <div class="control-table-cell">
                  {queue.candidates.length} candidates
                </div>
                <div class="control-table-cell actions">
                  <button type="button" class="ghost icon-only" title="Open overview" aria-label={`Open overview for ${queue.name}`} on:click|stopPropagation={() => openQueueOverview(queue)} disabled={actionBusy}>
                    <BarChart2 size={16} />
                  </button>
                  <button type="button" class="ghost icon-only" title={`Edit ${queue.name}`} aria-label={`Edit ${queue.name}`} on:click|stopPropagation={() => openEditModelQueueModal(queue)} disabled={actionBusy}>
                    <Pencil size={15} />
                  </button>
                  <button type="button" class="btn-danger icon-only" title={`Delete ${queue.name}`} aria-label={`Delete ${queue.name}`} on:click|stopPropagation={() => handleDeleteModelQueue(queue.id)} disabled={actionBusy}>
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>
            {/each}
            {#if !filteredModelQueues.length}
              <p class="muted" style="padding: 1rem; text-align: center; margin: 0;">No model queues yet.</p>
            {/if}
          </div>
        </section>
      {/if}

      {#if activeSection === 'usage'}
        <section class="section-block">
        <div class="section-shell">
          <div class="section-column">
            <div class="section-toolbar">
              <button
                type="button"
                class="ghost"
                on:click={() => (showUsageFilters = !showUsageFilters)}
                style="display: inline-flex; align-items: center; gap: 0.4rem;"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  width="14"
                  height="14"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="2"
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  style="opacity: 0.7;"
                >
                  <polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3" />
                </svg>
                {showUsageFilters ? 'Hide Filters' : 'Show Filters'}
              </button>
              <button type="button" on:click={handleApplyFilters} disabled={loading} style="margin-left: auto;">
                Refresh Logs
              </button>
            </div>

            {#if showUsageFilters}
              <div class="filter-grid" style="margin-top: 0.75rem; margin-bottom: 0.75rem;">
                <label>
                  App token
                  <select bind:value={usageAppTokenFilter} on:change={handleApplyFilters}>
                    <option value="">All apps</option>
                    {#each appTokens as appToken}
                      <option value={String(appToken.id)}>{appToken.name}</option>
                    {/each}
                  </select>
                </label>
                <label>
                  Provider key
                  <select bind:value={usageProviderKeyFilter} on:change={handleApplyFilters}>
                    <option value="">All keys</option>
                    {#each providerKeys as providerKey}
                      <option value={String(providerKey.id)}>{providerKey.name}</option>
                    {/each}
                  </select>
                </label>
                <label>
                  Queue
                  <select bind:value={usageQueueFilter} on:change={handleApplyFilters}>
                    <option value="">All queues</option>
                    {#each modelQueues as queue}
                      <option value={queue.name}>{queue.name}</option>
                    {/each}
                  </select>
                </label>
                <label>
                  Protocol in
                  <select bind:value={usageProtocolInFilter} on:change={handleApplyFilters}>
                    <option value="">All inputs</option>
                    <option value="openai">OpenAI</option>
                    <option value="anthropic">Anthropic</option>
                  </select>
                </label>
                <label>
                  Protocol out
                  <select bind:value={usageProtocolOutFilter} on:change={handleApplyFilters}>
                    <option value="">All outputs</option>
                    <option value="openai">OpenAI</option>
                    <option value="anthropic">Anthropic</option>
                  </select>
                </label>
                <label>
                  Route kind
                  <select bind:value={usageRouteKindFilter} on:change={handleApplyFilters}>
                    <option value="">All routes</option>
                    <option value="provider">Provider</option>
                    <option value="queue">Queue</option>
                  </select>
                </label>
                <label>
                  Tool calling
                  <select bind:value={usageToolCallingFilter} on:change={handleApplyFilters}>
                    <option value="">All</option>
                    <option value="true">Yes</option>
                    <option value="false">No</option>
                  </select>
                </label>
                <label>
                  Page size
                  <input bind:value={usageLimit} type="number" min="1" max="500" on:change={handleApplyFilters} />
                </label>
              </div>
            {/if}

        <div class="metric-strip compact">
          <div class="metric-card">
            <span>App token</span>
            <strong>{formatTopMetric(usageAppTokenCounts)}</strong>
          </div>
          <div class="metric-card">
            <span>Provider key</span>
            <strong>{formatTopMetric(usageProviderKeyCounts)}</strong>
          </div>
          <div class="metric-card">
            <span>Provider</span>
            <strong>{formatTopMetric(usageProviderCounts)}</strong>
          </div>
          <div class="metric-card">
            <span>Model</span>
            <strong>{formatTopMetric(usageModelCounts)}</strong>
          </div>
        </div>

        <div class="usage-pagination">
          <div class="usage-pagination-summary">
            {#if usageTotalLogs}
              Showing {usageStartIndex}-{usageEndIndex} of {usageTotalLogs}
            {:else}
              No usage logs
            {/if}
          </div>
          <div class="usage-pagination-controls">
            <button
              type="button"
              class="ghost"
              on:click={() => setUsagePage(usageCurrentPage - 1)}
              disabled={loading || usageCurrentPage <= 1}
            >
              Previous
            </button>
            <button
              type="button"
              class="ghost"
              on:click={() => setUsagePage(usageCurrentPage + 1)}
              disabled={loading || usageCurrentPage >= usageTotalPages || !usageTotalLogs}
            >
              Next
            </button>
          </div>
        </div>

        <div class="control-table">
          <div class="control-table-head grid-usage-logs">
            <div class="control-table-cell">Timestamp</div>
            <div class="control-table-cell">App Token</div>
            <div class="control-table-cell">Provider</div>
            <div class="control-table-cell">Provider Key</div>
            <div class="control-table-cell">Model Path</div>
            <div class="control-table-cell">Status</div>
            <div class="control-table-cell">Tokens</div>
            <div class="control-table-cell">Latency</div>
          </div>

          {#each usageLogs as log}
            <div
              class="control-table-row grid-usage-logs selectable"
              role="button"
              tabindex="0"
              on:click={() => openUsageLog(log)}
              on:keydown={(event) => handleCardKeydown(event, () => openUsageLog(log))}
            >
              <div class="control-table-cell" style="opacity: 0.8;">
                {formatDate(log.created_at)}
              </div>
              <div class="control-table-cell">
                <strong>{log.app_token_name ?? 'Unknown app'}</strong>
              </div>
              <div class="control-table-cell" style="text-transform: capitalize;">
                {log.provider_used}
              </div>
              <div class="control-table-cell" style="opacity: 0.85;">
                {log.provider_key_name ?? 'Unknown key'}
              </div>
              <div class="control-table-cell">
                {log.resolved_model ?? log.model_requested}
              </div>
              <div class="control-table-cell">
                <span class="badge {log.status_code >= 400 ? 'badge-bad' : log.was_rotated ? 'badge-warn' : 'badge-good'}">
                  {formatUsageStatus(log)}
                </span>
              </div>
              <div class="control-table-cell">
                {formatMetric(log.total_tokens)}
              </div>
              <div class="control-table-cell">
                {formatMetric(log.latency_ms, 0)} ms
              </div>
            </div>
          {/each}
          {#if !usageLogs.length}
            <p class="muted" style="padding: 1rem; text-align: center; margin: 0;">No usage logs yet.</p>
          {/if}
        </div>
          </div>
        </div>

        {#if selectedUsageLog}
          <div class="modal-backdrop" on:click={closeUsageLog} on:keydown={(e) => e.key === 'Escape' && closeUsageLog()} tabindex="0" role="button">
            <div class="modal-content" on:click|stopPropagation on:keydown|stopPropagation tabindex="-1" role="dialog" aria-modal="true" style="max-width: 760px;">
              <div class="modal-header">
                <h3>Usage log</h3>
                <button type="button" class="ghost" on:click={closeUsageLog}>Close</button>
              </div>
              <div class="modal-body">
                <div class="detail-grid compact">
                  <div>
                    <span>App token</span>
                    <strong>{selectedUsageLog.app_token_name ?? 'Unknown app'}</strong>
                  </div>
                  <div>
                    <span>Queue</span>
                    <strong>{selectedUsageLog.queue_name ?? 'None'}</strong>
                  </div>
                  <div>
                    <span>Protocol in</span>
                    <strong>{selectedUsageLog.protocol_in}</strong>
                  </div>
                  <div>
                    <span>Protocol out</span>
                    <strong>{selectedUsageLog.protocol_out}</strong>
                  </div>
                  <div>
                    <span>Route kind</span>
                    <strong>{selectedUsageLog.route_kind}</strong>
                  </div>
                  <div>
                    <span>Model</span>
                    <strong>{selectedUsageLog.resolved_model ?? selectedUsageLog.model_requested}</strong>
                  </div>
                  <div>
                    <span>Provider</span>
                    <strong>{selectedUsageLog.provider_used}</strong>
                  </div>
                  <div>
                    <span>Provider key</span>
                    <strong>{selectedUsageLog.provider_key_name ?? 'Unknown key'}</strong>
                  </div>
                  <div>
                    <span>Status</span>
                    <strong class="badge {selectedUsageLog.status_code >= 400 ? 'badge-bad' : selectedUsageLog.was_rotated ? 'badge-warn' : 'badge-good'}">{formatUsageStatus(selectedUsageLog)}</strong>
                  </div>
                  <div>
                    <span>Tool calling</span>
                    <strong>{selectedUsageLog.tool_calling ? 'Yes' : 'No'}</strong>
                  </div>
                  <div>
                    <span>Requested model</span>
                    <strong>{selectedUsageLog.model_requested}</strong>
                  </div>
                  <div>
                    <span>Created</span>
                    <strong>{formatDate(selectedUsageLog.created_at)}</strong>
                  </div>
                </div>
                <div class="json-panel" style="margin-top: 1rem;">
                  <pre>{JSON.stringify(selectedUsageLog, null, 2)}</pre>
                </div>
              </div>
            </div>
          </div>
        {/if}
        </section>
      {/if}

      {#if activeSection === 'runtime'}
        <section class="section-block">
          <div class="split-panels">
            <div class="panel-surface">
              <div class="panel-head">
                <h3>Runtime</h3>
                <p>Backend host and port.</p>
              </div>

              <p class="runtime-note">
                Use provider/model aliases like <code>google/gemini-3.1-flash</code>, <code>openai/gpt-4o-mini</code>,
                or use generic tokens to let the rotator pick any valid key based on rate limits.
              </p>

              <div class="form-grid runtime-grid" style="max-width: 600px;">
                <label>
                  Host
                  <input bind:value={runtimeHost} type="text" placeholder="127.0.0.1" />
                </label>
                <label>
                  Port
                  <input bind:value={runtimePort} type="number" min="1" max="65535" />
                </label>
              </div>
              <button type="button" class="primary" on:click={handleRuntimeSave} disabled={loading} style="max-width: max-content; margin-top: 1rem;">
                Save runtime settings
              </button>

              {#if runtimeConfig}
                <p class="muted">
                  Current API base: <code>{runtimeConfig.api_base_url}</code>
                </p>
              {/if}
              {#if restartPending}
                <p class="muted">Restart pending. The UI will reconnect after the backend service comes back up.</p>
              {/if}
            </div>

            <div class="panel-surface">
              <div class="panel-head">
                <h3>Alerts</h3>
                <p>Telegram and alert routing.</p>
              </div>

              <div class="runtime-strip compact">
                <div class="chip">{alertSettings?.telegram_enabled ? 'Telegram on' : 'Telegram off'}</div>
                <div class="muted">{alertSettings?.telegram_chat_id ? `Chat ${alertSettings.telegram_chat_id}` : 'No chat configured'}</div>
              </div>

              <p class="runtime-note">
                Configure Telegram here and choose which operational events should trigger alerts.
              </p>

              <div class="form-grid runtime-grid" style="max-width: 720px;">
                <label class="checkbox-row wide">
                  <span>Telegram enabled</span>
                  <input bind:checked={alertTelegramEnabled} type="checkbox" />
                </label>
                <label class="wide">
                  Telegram bot token
                  <input bind:value={alertTelegramBotToken} type="password" placeholder={alertSettings?.telegram_bot_token_configured ? 'Leave blank to keep current token' : 'Enter Telegram bot token'} />
                </label>
                <label class="wide">
                  Telegram chat ID
                  <input bind:value={alertTelegramChatId} type="text" placeholder="123456789" />
                </label>
              </div>

              <div class="form-grid alerts-grid" style="max-width: 720px; margin-top: 1rem;">
                <label class="checkbox-row">
                  <span>Proxy failures</span>
                  <input bind:checked={alertProxyFailures} type="checkbox" />
                </label>
                <label class="checkbox-row">
                  <span>Queue exhausted</span>
                  <input bind:checked={alertQueueExhausted} type="checkbox" />
                </label>
                <label class="checkbox-row">
                  <span>Provider pool exhausted</span>
                  <input bind:checked={alertProviderPoolExhausted} type="checkbox" />
                </label>
                <label class="checkbox-row">
                  <span>Provider key status changes</span>
                  <input bind:checked={alertProviderKeyStatusChanges} type="checkbox" />
                </label>
              </div>

              <button type="button" class="primary" on:click={handleAlertSettingsSave} disabled={loading || actionBusy} style="max-width: max-content; margin-top: 1rem;">
                Save alert settings
              </button>
              <button
                type="button"
                class="ghost"
                on:click={handleTelegramTest}
                disabled={loading || actionBusy || alertTestBusy || !telegramTestReady}
                style="max-width: max-content; margin-top: 0.75rem;"
              >
                {alertTestBusy ? 'Sending test...' : 'Test Telegram'}
              </button>
              {#if alertError}
                <p class="muted">{alertError}</p>
              {/if}
              {#if alertSettings}
                <p class="muted">
                  Last updated: {formatDate(alertSettings.updated_at)}
                </p>
              {/if}
            </div>
          </div>
        </section>
      {/if}



<style>
  @import './new_style.css';
</style>
