<script lang="ts">
  import { Bar, Line } from 'svelte-chartjs';
  import {
    Chart,
    Title,
    Tooltip,
    LineElement,
    PointElement,
    CategoryScale,
    LinearScale,
    Filler,
    ArcElement,
    BarElement,
    Legend
  } from 'chart.js';
  import type { ChartOptions } from 'chart.js';
  import type { OverviewDetail } from '$lib/api';
  import type { OverviewRange } from '$lib/overview';

  Chart.register(Title, Tooltip, Legend, LineElement, PointElement, CategoryScale, LinearScale, Filler, ArcElement, BarElement);

  export let detail: OverviewDetail | null = null;
  export let loading = false;
  export let error = '';
  export let title = '';
  export let fallbackLabel = '';
  export let backHref = '/app';
  export let range: OverviewRange = '24h';
  export let onRangeChange: (nextRange: OverviewRange) => void = () => {};

  function formatMetric(value: number, fractionDigits = 0) {
    return new Intl.NumberFormat('en-US', {
      maximumFractionDigits: fractionDigits,
      minimumFractionDigits: fractionDigits
    }).format(value);
  }

  function formatContextType(value: string | undefined) {
    if (value === 'app_token') {
      return 'App token';
    }
    if (value === 'provider_key') {
      return 'Provider key';
    }
    if (value === 'model-queue' || value === 'queue') {
      return 'Queue';
    }
    if (value === 'provider') {
      return 'Provider';
    }
    return value ?? 'Overview';
  }

  function formatContextScope(detail: OverviewDetail | null) {
    if (!detail) {
      return 'Filtered overview';
    }
    if (detail.context_type === 'app_token') {
      return `App token #${detail.context_id ?? 'n/a'}`;
    }
    if (detail.context_type === 'provider_key') {
      return `Provider key ${detail.context_label}`;
    }
    if (detail.context_type === 'provider') {
      return `Provider ${detail.context_label}`;
    }
    if (detail.context_type === 'queue') {
      return `Queue ${detail.context_label}`;
    }
    return detail.context_label;
  }

  function formatChartBucketLabel(value: string, granularity: string | undefined) {
    const date = new Date(value);
    if (granularity === 'minute') {
      return new Intl.DateTimeFormat('en-US', {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
        timeZone: 'America/Sao_Paulo'
      }).format(date);
    }

    if (granularity === 'day') {
      return new Intl.DateTimeFormat('en-US', {
        month: 'short',
        day: 'numeric',
        timeZone: 'America/Sao_Paulo'
      }).format(date);
    }

    return new Intl.DateTimeFormat('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
      timeZone: 'America/Sao_Paulo'
    }).format(date);
  }

  $: buckets = detail?.timeseries.buckets ?? [];
  $: labels = buckets.map((bucket) => formatChartBucketLabel(bucket.bucket_start, detail?.timeseries.granularity));
  $: requestsSeries = buckets.map((bucket) => bucket.requests_count);
  $: errorsSeries = buckets.map((bucket) => bucket.error_count);
  $: latencySeries = buckets.map((bucket) => bucket.avg_latency_ms);
  $: tokensSeries = buckets.map((bucket) => bucket.total_tokens_consumed);
  $: totalRequests = buckets.reduce((sum, bucket) => sum + bucket.requests_count, 0);
  $: totalSuccess = buckets.reduce((sum, bucket) => sum + bucket.success_count, 0);
  $: totalErrors = buckets.reduce((sum, bucket) => sum + bucket.error_count, 0);
  $: totalTokens = buckets.reduce((sum, bucket) => sum + bucket.total_tokens_consumed, 0);
  $: avgLatency = buckets.length ? buckets.reduce((sum, bucket) => sum + bucket.avg_latency_ms, 0) / buckets.length : 0;
  $: topModels = (detail?.models ?? []).slice(0, 8);
  $: modelLabels = topModels.map((model) => model.model_name);
  $: modelSeries = topModels.map((model) => model.requests_count);
  $: topModelEntry = topModels[0] ?? null;

  $: lineData = {
    labels,
    datasets: [
      {
        label: 'Requests',
        data: requestsSeries,
        borderColor: '#d8b858',
        backgroundColor: 'rgba(216, 184, 88, 0.1)',
        tension: 0.35,
        fill: true
      },
      {
        label: 'Errors',
        data: errorsSeries,
        borderColor: '#ef4444',
        backgroundColor: 'rgba(239, 68, 68, 0.1)',
        tension: 0.35,
        fill: true
      },
      {
        label: 'Latency',
        data: latencySeries,
        borderColor: '#f59e0b',
        backgroundColor: 'rgba(245, 158, 11, 0.1)',
        tension: 0.35,
        fill: true,
        yAxisID: 'latency'
      }
    ]
  };

  $: modelsData = {
    labels: modelLabels,
    datasets: [
      {
        label: 'Requests',
        data: modelSeries,
        borderColor: '#d8b858',
        backgroundColor: 'rgba(216, 184, 88, 0.2)',
        borderWidth: 1.2
      }
    ]
  };

  const lineOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: true, position: 'bottom' as const }
    },
    scales: {
      x: {
        ticks: {
          color: '#9aa4b2',
          maxRotation: 0,
          autoSkip: true
        },
        grid: {
          color: 'rgba(255,255,255,0.05)'
        }
      },
      y: {
        ticks: {
          color: '#9aa4b2'
        },
        grid: {
          color: 'rgba(255,255,255,0.05)'
        }
      },
      latency: {
        position: 'right' as const,
        ticks: {
          color: '#9aa4b2'
        },
        grid: {
          drawOnChartArea: false
        }
      }
    }
  } satisfies ChartOptions<'line'>;

  const barOptions = {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: { display: false }
    },
    scales: {
      x: {
        ticks: {
          color: '#9aa4b2',
          maxRotation: 0,
          autoSkip: true
        },
        grid: {
          color: 'rgba(255,255,255,0.05)'
        }
      },
      y: {
        ticks: {
          color: '#9aa4b2'
        },
        grid: {
          color: 'rgba(255,255,255,0.05)'
        }
      }
    }
  } satisfies ChartOptions<'bar'>;
</script>

<section class="overview-page">
  <header class="overview-page-header">
    <div class="overview-header-copy">
      <a class="overview-back-link" href={backHref}>← Back</a>
      <p class="overview-eyebrow">{formatContextType(detail?.context_type)}</p>
      <h1>{title}</h1>
      <p class="overview-label">{detail?.context_label ?? fallbackLabel}</p>
    </div>

    <div class="overview-header-tools">
      <div class="range-switch compact">
        <button type="button" class:active={range === '1h'} on:click={() => onRangeChange('1h')}>1h</button>
        <button type="button" class:active={range === '24h'} on:click={() => onRangeChange('24h')}>24h</button>
        <button type="button" class:active={range === '7d'} on:click={() => onRangeChange('7d')}>7d</button>
        <button type="button" class:active={range === '30d'} on:click={() => onRangeChange('30d')}>30d</button>
      </div>
    </div>
  </header>

  <div class="overview-scope-bar">
    <div>
      <span>Scope</span>
      <strong>{formatContextScope(detail)}</strong>
    </div>
    <div>
      <span>Window</span>
      <strong>{range}</strong>
    </div>
    <div>
      <span>Granularity</span>
      <strong>{detail?.timeseries.granularity ?? 'n/a'}</strong>
    </div>
    <div>
      <span>Requests</span>
      <strong>{detail?.summary.total_requests ?? 0}</strong>
    </div>
  </div>

  <div class="overview-telemetry-grid">
    <div class="overview-telemetry-card">
      <span>Scope</span>
      <strong>{formatContextType(detail?.context_type)}</strong>
    </div>
    <div class="overview-telemetry-card">
      <span>Target</span>
      <strong>{detail?.context_label ?? 'None'}</strong>
    </div>
    <div class="overview-telemetry-card">
      <span>Top model</span>
      <strong>{topModelEntry ? `${topModelEntry.model_name} ${topModelEntry.requests_count}` : 'None'}</strong>
    </div>
    <div class="overview-telemetry-card">
      <span>Requests</span>
      <strong>{detail?.summary.total_requests ?? 0}</strong>
    </div>
  </div>

  {#if loading}
    <div class="overview-state">
      <strong>Loading overview…</strong>
      <p>Fetching metrics, timeseries and model breakdown.</p>
    </div>
  {:else if error}
    <div class="overview-state error">{error}</div>
  {:else if detail}
    {#if detail.summary.total_requests === 0}
      <div class="overview-state">
        <strong>No traffic in this scope.</strong>
        <p>The selected app, provider, or queue has no usage in the chosen window.</p>
      </div>
    {/if}
    <div class="overview-summary-grid">
      <div class="overview-summary-card">
        <span>Requests</span>
        <strong>{formatMetric(detail.summary.total_requests)}</strong>
      </div>
      <div class="overview-summary-card">
        <span>Success rate</span>
        <strong>{formatMetric(detail.summary.success_rate, 1)}%</strong>
      </div>
      <div class="overview-summary-card">
        <span>Latency</span>
        <strong>{detail.summary.avg_latency_ms.toFixed(1)}ms</strong>
      </div>
      <div class="overview-summary-card">
        <span>Tokens</span>
        <strong>{formatMetric(detail.summary.total_tokens_consumed)}</strong>
      </div>
      <div class="overview-summary-card">
        <span>Rotations</span>
        <strong>{formatMetric(detail.summary.total_rotations_triggered)}</strong>
      </div>
    </div>

    <div class="overview-charts">
      <div class="overview-panel">
        <div class="overview-panel-header">
          <h3>Activity</h3>
          <span>requests</span>
        </div>
        <div class="overview-chart">
          {#if buckets.length}
            <Line data={lineData} options={lineOptions} />
          {:else}
            <div class="overview-empty">No data</div>
          {/if}
        </div>
        <div class="overview-axis">
          <span>{buckets[0] ? formatChartBucketLabel(buckets[0].bucket_start, detail.timeseries.granularity) : ''}</span>
          <span>{buckets[buckets.length - 1] ? formatChartBucketLabel(buckets[buckets.length - 1].bucket_end, detail.timeseries.granularity) : ''}</span>
        </div>
      </div>

      <div class="overview-panel">
        <div class="overview-panel-header">
          <h3>Models used</h3>
          <span>top 8</span>
        </div>
        <div class="overview-chart">
          {#if topModels.length}
            <Bar data={modelsData} options={barOptions} />
          {:else}
            <div class="overview-empty">No models yet</div>
          {/if}
        </div>
      </div>
    </div>

    <div class="overview-models">
      <div class="overview-panel-header">
        <h3>Models used</h3>
        <span>{detail.models.length} total</span>
      </div>
      <div class="overview-model-list">
        {#if detail.models.length}
          {#each detail.models as model}
            <div class="overview-model-row">
              <div>
                <strong>{model.model_name}</strong>
                <p>{model.requests_count} requests · {model.success_count} success · {model.error_count} errors</p>
              </div>
              <div class="overview-model-meta">
                <span>{formatMetric(model.total_tokens_consumed)} tokens</span>
                <span>{model.avg_latency_ms.toFixed(1)} ms</span>
              </div>
            </div>
          {/each}
        {:else}
          <p class="overview-empty-text">No model usage yet for this scope.</p>
        {/if}
      </div>
    </div>
  {/if}
</section>

<style>
  .overview-page {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    padding: 1.25rem 1.25rem 2rem;
  }

  .overview-page-header {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
    padding: 1rem 1.1rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: rgba(16, 19, 24, 0.9);
    backdrop-filter: blur(18px);
  }

  .overview-header-copy {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    min-width: 0;
  }

  .overview-back-link {
    color: var(--accent);
    text-decoration: none;
    font-size: 0.84rem;
    width: fit-content;
  }

  .overview-eyebrow {
    margin: 0;
    text-transform: uppercase;
    letter-spacing: 0.18em;
    font-size: 0.72rem;
    color: var(--muted);
  }

  .overview-page-header h1 {
    margin: 0;
    font-size: clamp(1.5rem, 2vw, 2rem);
    line-height: 1.1;
  }

  .overview-label {
    margin: 0;
    color: var(--muted);
    font-size: 0.92rem;
  }

  .overview-header-tools {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }

  .overview-scope-bar {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 0.75rem;
    padding: 0.9rem 1rem;
    border: 1px solid var(--border);
    border-radius: 8px;
    background: rgba(16, 19, 24, 0.72);
    backdrop-filter: blur(16px);
  }

  .overview-scope-bar > div {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    min-width: 0;
  }

  .overview-scope-bar span {
    text-transform: uppercase;
    letter-spacing: 0.12em;
    font-size: 0.68rem;
    color: var(--muted);
  }

  .overview-scope-bar strong {
    font-size: 0.92rem;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .overview-summary-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 0.75rem;
  }

  .overview-telemetry-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
    gap: 0.75rem;
    margin-top: 0.75rem;
  }

  .overview-summary-card,
  .overview-telemetry-card,
  .overview-panel,
  .overview-models,
  .overview-state {
    border: 1px solid var(--border);
    border-radius: 8px;
    background: rgba(16, 19, 24, 0.88);
    backdrop-filter: blur(16px);
  }

  .overview-summary-card {
    padding: 0.9rem 1rem;
  }

  .overview-summary-card span {
    display: block;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--muted);
    margin-bottom: 0.35rem;
  }

  .overview-summary-card strong {
    font-size: 1.65rem;
    line-height: 1.1;
  }

  .overview-telemetry-card {
    padding: 0.85rem 0.95rem;
  }

  .overview-telemetry-card span {
    display: block;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.12em;
    color: var(--muted);
    margin-bottom: 0.35rem;
  }

  .overview-telemetry-card strong {
    font-size: 0.95rem;
    line-height: 1.35;
  }

  .overview-charts {
    display: grid;
    grid-template-columns: minmax(0, 2fr) minmax(0, 1fr);
    gap: 0.75rem;
  }

  .overview-panel {
    padding: 0.9rem 1rem;
  }

  .overview-panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    margin-bottom: 0.8rem;
  }

  .overview-panel-header h3 {
    margin: 0;
    font-size: 0.98rem;
  }

  .overview-panel-header span {
    font-size: 0.75rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.12em;
  }

  .overview-chart {
    height: 240px;
    position: relative;
  }

  .overview-axis {
    display: flex;
    justify-content: space-between;
    gap: 0.5rem;
    margin-top: 0.65rem;
    color: var(--muted);
    font-size: 0.75rem;
  }

  .overview-models {
    padding: 0.9rem 1rem;
  }

  .overview-model-list {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }

  .overview-model-row {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.8rem 0;
    border-top: 1px solid var(--border);
  }

  .overview-model-row:first-child {
    border-top: 0;
    padding-top: 0;
  }

  .overview-model-row strong {
    display: block;
    margin-bottom: 0.2rem;
  }

  .overview-model-row p,
  .overview-empty-text {
    margin: 0;
    color: var(--muted);
    font-size: 0.88rem;
  }

  .overview-model-meta {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    align-items: flex-end;
    color: var(--muted);
    font-size: 0.82rem;
    white-space: nowrap;
  }

  .overview-state {
    padding: 1rem;
    color: var(--muted);
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }

  .overview-state strong {
    color: var(--text);
  }

  .overview-state.error {
    color: #ffb4b4;
  }

  .overview-empty {
    height: 100%;
    display: grid;
    place-items: center;
    color: var(--muted);
    font-style: italic;
    border: 1px dashed var(--border);
    border-radius: 8px;
  }

  @media (max-width: 1024px) {
    .overview-charts {
      grid-template-columns: 1fr;
    }

    .overview-scope-bar {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }

  @media (max-width: 720px) {
    .overview-page {
      padding: 0.9rem;
    }

    .overview-page-header {
      flex-direction: column;
      align-items: stretch;
    }

    .overview-header-tools {
      justify-content: flex-start;
    }

    .overview-scope-bar {
      grid-template-columns: 1fr;
    }

    .overview-model-row {
      flex-direction: column;
    }

    .overview-model-meta {
      align-items: flex-start;
    }
  }
</style>
