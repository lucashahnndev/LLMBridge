import {
  fetchAppTokenOverview,
  fetchProviderKeyOverview,
  fetchQueueOverview,
  type OverviewDetail
} from '$lib/api';

export type OverviewRouteKind = 'app-token' | 'provider-key' | 'model-queue';
export type OverviewRange = '1h' | '24h' | '7d' | '30d';

export function overviewPageTitle(kind: OverviewRouteKind) {
  if (kind === 'app-token') {
    return 'App token overview';
  }
  if (kind === 'provider-key') {
    return 'Provider key overview';
  }
  return 'Queue overview';
}

export function overviewRouteHref(kind: OverviewRouteKind, identifier: number | string) {
  return `/app/overview/${kind}/${encodeURIComponent(String(identifier))}`;
}

export async function loadOverviewDetail(
  token: string,
  kind: OverviewRouteKind,
  identifier: string,
  range: OverviewRange = '24h'
): Promise<OverviewDetail> {
  if (kind === 'app-token') {
    const appTokenId = Number(identifier);
    if (!Number.isFinite(appTokenId)) {
      throw new Error(`Invalid app token identifier: ${identifier}`);
    }
    return fetchAppTokenOverview(token, appTokenId, range);
  }

  if (kind === 'provider-key') {
    const providerKeyId = Number(identifier);
    if (!Number.isFinite(providerKeyId)) {
      throw new Error(`Invalid provider key identifier: ${identifier}`);
    }
    return fetchProviderKeyOverview(token, providerKeyId, range);
  }

  if (kind === 'model-queue') {
    return fetchQueueOverview(token, identifier, range);
  }

  throw new Error(`Unsupported overview kind: ${kind}`);
}
