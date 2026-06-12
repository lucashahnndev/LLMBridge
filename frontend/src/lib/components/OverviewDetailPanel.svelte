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
  import { formatOverviewTimeLabel } from '$lib/formatting';

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

  $: buckets = detail?.timeseries.buckets ?? [];
  $: labels = buckets.map((bucket) => formatOverviewTimeLabel(bucket.bucket_start, range));
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

<section class="section-block" style="padding: 1.25rem 1.25rem 2rem;">
  <div class="section-title">
    <div style="display: flex; flex-direction: column; gap: 0.15rem;">
      <div style="display: flex; align-items: center; gap: 0.5rem; font-size: 0.75rem; color: var(--muted);">
        <a href={backHref} class="ghost-btn" style="color: var(--accent); text-decoration: none; display: inline-flex; align-items: center; gap: 0.25rem;">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m15 18-6-6 6-6"/></svg>
          Back
        </a>
        <span style="opacity: 0.4;">/</span>
        <span style="text-transform: uppercase; letter-spacing: 0.05em;">{title}</span>
      </div>
      <h2 style="font-size: 1.25rem; font-weight: 600; color: var(--text); margin-top: 0.25rem;">
        {detail?.context_label ?? fallbackLabel}
      </h2>
    </div>

    <div class="activity-filters" role="tablist">
      <button type="button" class="ghost" class:active={range === '1h'} on:click={() => onRangeChange('1h')}>1h</button>
      <button type="button" class="ghost" class:active={range === '24h'} on:click={() => onRangeChange('24h')}>24h</button>
      <button type="button" class="ghost" class:active={range === '7d'} on:click={() => onRangeChange('7d')}>7d</button>
      <button type="button" class="ghost" class:active={range === '30d'} on:click={() => onRangeChange('30d')}>30d</button>
    </div>
  </div>

  {#if loading}
    <div class="smart-empty">
      <strong>Loading overview…</strong>
      <p>Fetching metrics, timeseries and model breakdown.</p>
    </div>
  {:else if error}
    <div class="smart-empty" style="border-color: rgba(239, 68, 68, 0.2); background: rgba(239, 68, 68, 0.01);">
      <strong style="color: var(--bad);">Error loading overview</strong>
      <p style="color: var(--bad); opacity: 0.8;">{error}</p>
    </div>
  {:else if detail}
    <div class="metric-grid">
      <div class="metric-card">
        <span>Scope</span>
        <strong>{formatContextScope(detail)}</strong>
      </div>
      <div class="metric-card">
        <span>Granularity</span>
        <strong>{detail.timeseries.granularity ? `${range} / ${detail.timeseries.granularity}` : range}</strong>
      </div>
      <div class="metric-card">
        <span>Total requests</span>
        <strong>{formatMetric(detail.summary.total_requests)}</strong>
      </div>
      <div class="metric-card">
        <span>Success rate</span>
        <strong>{formatMetric(detail.summary.success_rate, 1)}%</strong>
      </div>
      <div class="metric-card">
        <span>Avg Latency</span>
        <strong>{detail.summary.avg_latency_ms.toFixed(1)}ms</strong>
      </div>
      <div class="metric-card">
        <span>Total tokens</span>
        <strong>{formatMetric(detail.summary.total_tokens_consumed)}</strong>
      </div>
      <div class="metric-card">
        <span>Rotations</span>
        <strong>{formatMetric(detail.summary.total_rotations_triggered)}</strong>
      </div>
      <div class="metric-card">
        <span>Error rate</span>
        <strong>{(100 - detail.summary.success_rate).toFixed(1)}%</strong>
      </div>
    </div>

    {#if detail.summary.total_requests === 0}
      <div class="smart-empty">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" style="opacity: 0.4;"><rect width="20" height="20" x="2" y="2" rx="5" ry="5"/><path d="M16 11.37A4 4 0 1 1 12.63 8 4 4 0 0 1 16 11.37z"/><line x1="17.5" x2="17.51" y1="6.5" y2="6.5"/></svg>
        <strong>No traffic in this scope</strong>
        <p>The selected item has no usage in the chosen window.</p>
      </div>
    {/if}

    <div class="dashboard-row cols-2">
      <!-- Activity / Usage over time -->
      <div class="dashboard-card">
        <div class="card-header">
          <div class="card-header-row">
            <h3>Activity</h3>
            <span class="chart-legend">requests</span>
          </div>
        </div>
        <div class="card-body" style="display: flex; flex-direction: column; gap: 0.5rem;">
          <div class="chart-panel" style="height: 240px; position: relative;">
            {#if buckets.length}
              <Line data={lineData} options={lineOptions} />
            {:else}
              <div class="chart-empty">No data</div>
            {/if}
          </div>
          <div class="chart-axis" style="margin-top: 0.25rem;">
            <span>{buckets[0] ? formatOverviewTimeLabel(buckets[0].bucket_start, range) : ''}</span>
            <span>{buckets[buckets.length - 1] ? formatOverviewTimeLabel(buckets[buckets.length - 1].bucket_end, range) : ''}</span>
          </div>
        </div>
      </div>

      <!-- Models Used Breakdown -->
      <div class="dashboard-card">
        <div class="card-header">
          <div class="card-header-row">
            <h3>Models Used</h3>
            <span class="chart-legend">top 8</span>
          </div>
        </div>
        <div class="card-body">
          <div class="chart-panel" style="height: 240px; position: relative;">
            {#if topModels.length}
              <Bar data={modelsData} options={barOptions} />
            {:else}
              <div class="chart-empty">No models yet</div>
            {/if}
          </div>
        </div>
      </div>
    </div>

    <!-- Models List Table Card -->
    <div class="dashboard-card" style="margin-top: 0.25rem;">
      <div class="card-header">
        <div class="card-header-row">
          <h3>Models Breakdown</h3>
          <span class="chart-legend accent">{detail.models.length} total</span>
        </div>
      </div>
      <div class="card-body" style="padding: 0;">
        <div class="control-table" style="border: none; border-radius: 0; box-shadow: none;">
          <div class="control-table-head grid-overview-models">
            <div class="control-table-cell">Model Name</div>
            <div class="control-table-cell">Requests</div>
            <div class="control-table-cell">Success</div>
            <div class="control-table-cell">Errors</div>
            <div class="control-table-cell">Avg Latency</div>
            <div class="control-table-cell">Tokens</div>
          </div>
          {#if detail.models.length}
            {#each detail.models as model}
              <div class="control-table-row grid-overview-models">
                <div class="control-table-cell" style="font-weight: 600; color: var(--text);">{model.model_name}</div>
                <div class="control-table-cell">{formatMetric(model.requests_count)}</div>
                <div class="control-table-cell" style="color: var(--good);">{formatMetric(model.success_count)}</div>
                <div class="control-table-cell" style="color: {model.error_count > 0 ? 'var(--bad)' : 'var(--muted)'};">
                  {formatMetric(model.error_count)}
                </div>
                <div class="control-table-cell">{model.avg_latency_ms.toFixed(1)} ms</div>
                <div class="control-table-cell" style="font-variant-numeric: tabular-nums;">{formatMetric(model.total_tokens_consumed)}</div>
              </div>
            {/each}
          {:else}
            <div class="smart-empty" style="margin: 1.5rem; border: 1px dashed var(--border);">
              No model usage yet for this scope.
            </div>
          {/if}
        </div>
      </div>
    </div>
  {/if}
</section>

<style>
  .grid-overview-models {
    grid-template-columns: minmax(180px, 2.5fr) minmax(80px, 1fr) minmax(80px, 1fr) minmax(80px, 1fr) minmax(90px, 1fr) minmax(110px, 1.2fr);
  }

  .chart-panel {
    position: relative;
    width: 100%;
  }

  .chart-axis {
    display: flex;
    justify-content: space-between;
    gap: 0.75rem;
    color: var(--muted);
    font-size: 0.68rem;
    font-variant-numeric: tabular-nums;
    font-weight: 500;
  }
</style>
