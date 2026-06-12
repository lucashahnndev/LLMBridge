<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import OverviewDetailPanel from '$lib/components/OverviewDetailPanel.svelte';
  import { getStoredAdminToken, type OverviewDetail } from '$lib/api';
  import { loadOverviewDetail, overviewPageTitle, type OverviewRange, type OverviewRouteKind } from '$lib/overview';
  import type { PageData } from './$types';

  export let data: PageData;

  let overviewKind: OverviewRouteKind = data.kind as OverviewRouteKind;
  let overviewTitle = overviewPageTitle(overviewKind);
  let overviewFallbackLabel = data.identifier;

  let token = '';
  let detail: OverviewDetail | null = null;
  let loading = true;
  let error = '';
  let range: OverviewRange = '24h';
  let previousIdentifier = data.identifier;
  let previousKind = data.kind;

  $: if (data.kind !== previousKind || data.identifier !== previousIdentifier) {
    previousKind = data.kind;
    previousIdentifier = data.identifier;
    overviewKind = data.kind as OverviewRouteKind;
    overviewTitle = overviewPageTitle(overviewKind);
    overviewFallbackLabel = overviewKind === 'app-token'
      ? `App token #${data.identifier}`
      : overviewKind === 'provider-key'
        ? `Provider key #${data.identifier}`
        : overviewKind === 'model-queue'
          ? data.identifier
          : data.identifier;
    detail = null;
    error = '';
    loading = Boolean(token);
    if (token) {
      void loadDetail();
    }
  }

  async function loadDetail() {
    if (!token) {
      return;
    }

    loading = true;
    error = '';
    try {
      detail = await loadOverviewDetail(token, overviewKind, data.identifier, range);
    } catch (loadError) {
      detail = null;
      error = loadError instanceof Error ? loadError.message : 'Failed to load overview';
    } finally {
      loading = false;
    }
  }

  function handleRangeChange(nextRange: OverviewRange) {
    range = nextRange;
    void loadDetail();
  }

  onMount(() => {
    const savedToken = getStoredAdminToken();
    if (!savedToken) {
      void goto('/login');
      return;
    }

    token = savedToken;
    void loadDetail();
  });
</script>

<svelte:head>
  <title>{overviewTitle} - LLMBridge</title>
  <meta
    name="description"
    content="Dedicated overview page for model usage, activity, and models used."
  />
</svelte:head>

<main class="overview-route-shell">
    <OverviewDetailPanel
    title={overviewTitle}
    fallbackLabel={overviewFallbackLabel}
    backHref="/app"
    {detail}
    {loading}
    {error}
    {range}
    onRangeChange={handleRangeChange}
  />
</main>

<style>
  .overview-route-shell {
    min-height: 100vh;
    background:
      radial-gradient(circle at top, rgba(216, 184, 88, 0.05), transparent 35%),
      #0c0d0f;
  }
</style>
