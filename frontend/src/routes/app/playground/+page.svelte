<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import {
    fetchAppTokens,
    fetchHealth,
    fetchModelQueues,
    fetchProviderKeys,
    fetchRuntimeConfig,
    fetchUsageLogs,
    getStoredAdminToken,
    type AppToken,
    type ModelQueue,
    type ProviderKey,
    type UsageLog
  } from '$lib/api';
  import { Copy, Check, ChevronLeft, RefreshCw, Sparkles, ShieldAlert } from 'lucide-svelte';

  type Protocol = 'anthropic' | 'openai';
  type TargetMode = 'queue' | 'provider-model' | 'custom';
  type CodeTab = 'curl' | 'json' | 'js';
  type CatalogStats = {
    appTokens: number;
    providerKeys: number;
    queues: number;
    recentModels: number;
  };
  type ResponseSummary = {
    status: number;
    statusText: string;
    latencyMs: number;
    headers: Array<[string, string]>;
    body: unknown;
    rawText: string;
    assistantText: string;
    toolCalls: Array<{ name: string; arguments: string }>;
  } | null;

  const DEFAULT_SYSTEM_PROMPT = 'You are a precise technical assistant. Keep answers short and operational.';
  const DEFAULT_USER_PROMPT = 'Explain how this gateway chooses a model when a key fails.';
  const DEFAULT_QUEUE = 'gemini';
  const DEFAULT_PROVIDER = 'google';
  const DEFAULT_MODEL = 'gemini-3.1-flash';
  const DEFAULT_CUSTOM_MODEL = 'queue/gemini';
  const DEFAULT_APP_TOKEN_PLACEHOLDER = 'lk-key-...';
  const KNOWN_PROVIDERS = ['google', 'openai', 'openrouter', 'anthropic'];
  const CATALOG_LIMIT = 50;

  let adminToken = '';
  let loadingCatalog = true;
  let catalogError = '';
  let requestError = '';
  let healthError = '';
  let healthStatus = '';
  let runtimeBaseUrl = 'http://127.0.0.1:8009';
  let runtimeHost = '127.0.0.1';
  let runtimePort = 8009;
  let catalogStats: CatalogStats = { appTokens: 0, providerKeys: 0, queues: 0, recentModels: 0 };
  let providerKeys: ProviderKey[] = [];
  let appTokens: AppToken[] = [];
  let modelQueues: ModelQueue[] = [];
  let usageLogs: UsageLog[] = [];

  let appTokenValue = '';
  let protocol: Protocol = 'anthropic';
  let targetMode: TargetMode = 'queue';
  let provider = DEFAULT_PROVIDER;
  let model = DEFAULT_MODEL;
  let queueName = DEFAULT_QUEUE;
  let customModel = DEFAULT_CUSTOM_MODEL;
  let systemPrompt = DEFAULT_SYSTEM_PROMPT;
  let userPrompt = DEFAULT_USER_PROMPT;
  let temperature = 0.2;
  let maxTokens = 256;
  let topP = 1;
  let toolCallingEnabled = true;
  let codeTab: CodeTab = 'curl';

  let requestRunning = false;
  let copiedSnippet = '';
  let responseSummary: ResponseSummary = null;
  let showRouteSettings = false;
  let showGenerationSettings = false;
  let showRequestCode = false;
  let showRawResponse = false;
  let showSystemPrompt = false;
  let showPromptTools = false;

  $: providerSuggestions = Array.from(
    new Set([
      ...KNOWN_PROVIDERS,
      ...providerKeys.map((key) => key.provider)
    ])
  ).filter(Boolean).sort();

  $: queueSuggestions = modelQueues
    .map((queue) => `queue/${queue.name}`)
    .sort((left, right) => left.localeCompare(right));

  $: modelSuggestions = Array.from(
    new Set([
      ...usageLogs.map((log) => log.model_requested),
      ...modelQueues.flatMap((queue) => queue.candidates.map((candidate) => `${candidate.provider}/${candidate.model_name}`))
    ])
  ).filter(Boolean).sort((left, right) => left.localeCompare(right));

  $: resolvedModel = buildResolvedModel();
  $: endpointPath = protocol === 'anthropic' ? '/v1/messages' : '/v1/chat/completions';
  $: requestUrl = `${proxyBaseUrl()}${endpointPath}`;
  $: requestPayload = buildRequestPayload();
  $: curlSnippet = buildCurlSnippet();
  $: jsSnippet = buildJsSnippet();
  $: jsonSnippet = JSON.stringify(requestPayload, null, 2);
  $: toolStatus = toolCallingEnabled ? 'tool calling enabled' : 'tool calling disabled';
  $: activeProfile = targetMode === 'queue'
    ? `queue/${queueName.trim().replace(/^queue\//, '') || '...' }`
    : targetMode === 'provider-model'
      ? `${provider.trim() || 'provider'}/${model.trim() || 'model'}`
      : customModel.trim() || 'custom';

  function proxyBaseUrl() {
    return runtimeBaseUrl.replace(/\/api\/v1$/, '');
  }

  function normalizeText(value: string) {
    return value.trim();
  }

  function buildResolvedModel() {
    if (targetMode === 'queue') {
      const normalizedQueue = normalizeText(queueName).replace(/^queue\//, '');
      return normalizedQueue ? `queue/${normalizedQueue}` : '';
    }

    if (targetMode === 'provider-model') {
      const normalizedProvider = normalizeText(provider);
      const normalizedModel = normalizeText(model);
      if (!normalizedProvider || !normalizedModel) {
        return '';
      }
      return `${normalizedProvider}/${normalizedModel}`;
    }

    return normalizeText(customModel);
  }

  function buildToolSpec() {
    if (!toolCallingEnabled) {
      return undefined;
    }

    const parameters = {
      type: 'object',
      properties: {
        scope: {
          type: 'string',
          enum: ['runtime', 'usage', 'queues']
        }
      },
      required: ['scope'],
      additionalProperties: false
    };

    if (protocol === 'anthropic') {
      return [
        {
          name: 'inspect_gateway',
          description: 'Inspect the gateway runtime, usage, or queue health.',
          input_schema: parameters
        }
      ];
    }

    return [
      {
        type: 'function',
        function: {
          name: 'inspect_gateway',
          description: 'Inspect the gateway runtime, usage, or queue health.',
          parameters
        }
      }
    ];
  }

  function buildRequestPayload() {
    const messages = [{ role: 'user', content: normalizeText(userPrompt) || DEFAULT_USER_PROMPT }];
    const payload: Record<string, unknown> = {
      model: resolvedModel,
      max_tokens: Math.max(1, Number(maxTokens) || 1),
      temperature: Number.isFinite(temperature) ? temperature : 0.2,
      top_p: Number.isFinite(topP) ? topP : 1,
      stream: false
    };

    if (protocol === 'anthropic') {
      if (normalizeText(systemPrompt)) {
        payload.system = normalizeText(systemPrompt);
      }
      payload.messages = messages;
    } else {
      const openAiMessages: Array<{ role: string; content: string }> = [];
      if (normalizeText(systemPrompt)) {
        openAiMessages.push({ role: 'system', content: normalizeText(systemPrompt) });
      }
      openAiMessages.push({ role: 'user', content: normalizeText(userPrompt) || DEFAULT_USER_PROMPT });
      payload.messages = openAiMessages;
    }

    const tools = buildToolSpec();
    if (tools) {
      payload.tools = tools;
      payload.tool_choice = 'auto';
    }

    return payload;
  }

  function escapeSingleQuotes(value: string) {
    return value.replaceAll("'", "'\\''");
  }

  function buildCurlSnippet() {
    const body = JSON.stringify(requestPayload, null, 2);
    return `curl -X POST ${requestUrl} \\
  -H "Authorization: Bearer ${appTokenValue || DEFAULT_APP_TOKEN_PLACEHOLDER}" \\
  -H "Content-Type: application/json" \\
  -d '${escapeSingleQuotes(body)}'`;
  }

  function buildJsSnippet() {
    return `const response = await fetch('${requestUrl}', {
  method: 'POST',
  headers: {
    Authorization: 'Bearer ${appTokenValue || DEFAULT_APP_TOKEN_PLACEHOLDER}',
    'Content-Type': 'application/json'
  },
  body: JSON.stringify(${JSON.stringify(requestPayload, null, 2)})
});

const data = await response.json();
console.log(data);`;
  }

  function formatMetric(value: number) {
    return new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 }).format(value);
  }

  function formatLatency(value: number) {
    return `${value.toFixed(1)} ms`;
  }

  function formatBodyText(body: unknown) {
    if (body === null || body === undefined) {
      return '';
    }

    if (typeof body === 'string') {
      return body;
    }

    if (typeof body !== 'object') {
      return String(body);
    }

    const value = body as Record<string, unknown>;
    const detail = value.detail;
    if (typeof detail === 'string') {
      return detail;
    }

    const error = value.error;
    if (error && typeof error === 'object') {
      const errorObject = error as Record<string, unknown>;
      if (typeof errorObject.message === 'string') {
        return errorObject.message;
      }
    }

    if (Array.isArray(value)) {
      return '';
    }

    return JSON.stringify(body, null, 2);
  }

  function extractAssistantText(body: unknown) {
    if (!body || typeof body !== 'object') {
      return '';
    }

    const value = body as Record<string, unknown>;

    if (Array.isArray(value.content)) {
      const textParts = value.content
        .filter((part): part is Record<string, unknown> => Boolean(part) && typeof part === 'object')
        .map((part) => {
          if (part.type === 'text' && typeof part.text === 'string') {
            return part.text;
          }
          if (part.type === 'tool_use' && typeof part.name === 'string') {
            return `Tool call requested: ${part.name}`;
          }
          return '';
        })
        .filter(Boolean);
      return textParts.join('\n').trim();
    }

    const choices = value.choices;
    if (Array.isArray(choices) && choices.length) {
      const firstChoice = choices[0];
      if (firstChoice && typeof firstChoice === 'object') {
        const choiceObject = firstChoice as Record<string, unknown>;
        const message = choiceObject.message;
        if (message && typeof message === 'object') {
          const messageObject = message as Record<string, unknown>;
          const content = messageObject.content;
          if (typeof content === 'string') {
            return content.trim();
          }
          if (Array.isArray(content)) {
            return content
              .filter((part): part is Record<string, unknown> => Boolean(part) && typeof part === 'object')
              .map((part) => (part.type === 'text' && typeof part.text === 'string' ? part.text : ''))
              .filter(Boolean)
              .join('\n')
              .trim();
          }
        }
      }
    }

    return '';
  }

  function extractToolCalls(body: unknown) {
    const results: Array<{ name: string; arguments: string }> = [];

    if (!body || typeof body !== 'object') {
      return results;
    }

    const value = body as Record<string, unknown>;

    if (Array.isArray(value.content)) {
      for (const part of value.content) {
        if (!part || typeof part !== 'object') {
          continue;
        }
        const block = part as Record<string, unknown>;
        if (block.type !== 'tool_use') {
          continue;
        }
        if (typeof block.name === 'string') {
          results.push({
            name: block.name,
            arguments: typeof block.input === 'string' ? block.input : JSON.stringify(block.input ?? {}, null, 2)
          });
        }
      }
    }

    const choices = value.choices;
    if (Array.isArray(choices) && choices.length) {
      const firstChoice = choices[0];
      if (firstChoice && typeof firstChoice === 'object') {
        const choiceObject = firstChoice as Record<string, unknown>;
        const message = choiceObject.message;
        if (message && typeof message === 'object') {
          const messageObject = message as Record<string, unknown>;
          const toolCalls = messageObject.tool_calls;
          if (Array.isArray(toolCalls)) {
            for (const call of toolCalls) {
              if (!call || typeof call !== 'object') {
                continue;
              }
              const callObject = call as Record<string, unknown>;
              const functionValue = callObject.function;
              if (!functionValue || typeof functionValue !== 'object') {
                continue;
              }
              const functionObject = functionValue as Record<string, unknown>;
              if (typeof functionObject.name !== 'string') {
                continue;
              }
              results.push({
                name: functionObject.name,
                arguments: typeof functionObject.arguments === 'string'
                  ? functionObject.arguments
                  : JSON.stringify(functionObject.arguments ?? {}, null, 2)
              });
            }
          }
        }
      }
    }

    return results;
  }

  function setProviderSuggestion(nextProvider: string) {
    provider = nextProvider;
  }

  function setModelSuggestion(nextModel: string) {
    model = nextModel;
  }

  function setQueueSuggestion(nextQueue: string) {
    queueName = nextQueue.replace(/^queue\//, '');
  }

  function setCustomTargetSuggestion(nextTarget: string) {
    customModel = nextTarget;
  }

  function copyText(text: string) {
    if (typeof navigator === 'undefined' || !navigator.clipboard) {
      return;
    }

    void navigator.clipboard.writeText(text);
    copiedSnippet = text;
    window.setTimeout(() => {
      if (copiedSnippet === text) {
        copiedSnippet = '';
      }
    }, 1800);
  }

  async function loadCatalog() {
    if (!adminToken) {
      return;
    }

    loadingCatalog = true;
    catalogError = '';
    healthError = '';

    try {
      const [health, runtime, apps, providers, queues, usage] = await Promise.all([
        fetchHealth(),
        fetchRuntimeConfig(adminToken),
        fetchAppTokens(adminToken, null),
        fetchProviderKeys(adminToken),
        fetchModelQueues(adminToken),
        fetchUsageLogs(adminToken, CATALOG_LIMIT)
      ]);

      healthStatus = `${health.service} ${health.status}`;
      runtimeBaseUrl = runtime.api_base_url.replace(/\/api\/v1$/, '');
      runtimeHost = runtime.host;
      runtimePort = runtime.port;
      appTokens = apps;
      providerKeys = providers;
      modelQueues = queues;
      usageLogs = usage.items;
      catalogStats = {
        appTokens: apps.length,
        providerKeys: providers.length,
        queues: queues.length,
        recentModels: new Set(usage.items.map((log) => log.model_requested)).size
      };

      if (!resolvedModel) {
        targetMode = 'queue';
        queueName = queues[0]?.name ?? DEFAULT_QUEUE;
      }
    } catch (error) {
      catalogError = error instanceof Error ? error.message : 'Failed to load playground catalog';
      healthStatus = '';
      healthError = 'unavailable';
    } finally {
      loadingCatalog = false;
    }
  }

  async function runRequest() {
    if (!adminToken) {
      requestError = 'Login again to use the playground.';
      return;
    }

    if (!appTokenValue.trim()) {
      requestError = 'Paste a valid app token first.';
      return;
    }

    if (!resolvedModel.trim()) {
      requestError = 'Select a target model or queue.';
      return;
    }

    requestRunning = true;
    requestError = '';
    responseSummary = null;

    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 60000);
    const started = performance.now();

    try {
      const response = await fetch(`${proxyBaseUrl()}${endpointPath}`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${appTokenValue.trim()}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(requestPayload),
        signal: controller.signal
      });

      const rawText = await response.text();
      let parsedBody: unknown = rawText;
      try {
        parsedBody = rawText ? JSON.parse(rawText) : null;
      } catch {
        parsedBody = rawText;
      }

      responseSummary = {
        status: response.status,
        statusText: response.statusText,
        latencyMs: performance.now() - started,
        headers: Array.from(response.headers.entries()),
        body: parsedBody,
        rawText,
        assistantText: extractAssistantText(parsedBody),
        toolCalls: extractToolCalls(parsedBody)
      };

      if (!response.ok) {
        requestError = formatBodyText(parsedBody) || `HTTP ${response.status}`;
      }
    } catch (error) {
      requestError = error instanceof Error ? error.message : 'Request failed';
      responseSummary = {
        status: 0,
        statusText: 'Client error',
        latencyMs: performance.now() - started,
        headers: [],
        body: { detail: requestError },
        rawText: requestError,
        assistantText: '',
        toolCalls: []
      };
    } finally {
      clearTimeout(timeout);
      requestRunning = false;
    }
  }

  function loadExample() {
    protocol = 'anthropic';
    targetMode = 'queue';
    queueName = 'gemini';
    appTokenValue = 'lk-key-your-app-token-here';
    systemPrompt = DEFAULT_SYSTEM_PROMPT;
    userPrompt = 'Use the configured queue and explain which target would be tried first.';
    temperature = 0.2;
    maxTokens = 256;
    topP = 1;
    toolCallingEnabled = true;
    codeTab = 'curl';
    showRawResponse = false;
    showSystemPrompt = false;
    showPromptTools = false;
    showRouteSettings = false;
    showGenerationSettings = false;
    showRequestCode = false;
  }

  function selectTargetPreset(value: string) {
    if (value.startsWith('queue/')) {
      targetMode = 'queue';
      queueName = value.slice('queue/'.length);
      return;
    }

    if (value.includes('/')) {
      const [nextProvider, ...rest] = value.split('/');
      if (nextProvider && rest.length) {
        targetMode = 'provider-model';
        provider = nextProvider;
        model = rest.join('/');
        return;
      }
    }

    targetMode = 'custom';
    customModel = value;
  }

  onMount(() => {
    const savedToken = getStoredAdminToken();
    if (!savedToken) {
      void goto('/login');
      return;
    }

    adminToken = savedToken;
    void loadCatalog();
  });
</script>

<svelte:head>
  <title>Playground - LLMBridge</title>
  <meta
    name="description"
    content="Technical playground for testing app tokens, queues, providers and model routing."
  />
</svelte:head>

<main class="playground-shell">
  <header class="playground-topbar">
    <div class="topbar-left">
      <button class="back-button" type="button" on:click={() => goto('/app')}>
        <ChevronLeft size={16} strokeWidth={1.8} />
        <span>Dashboard</span>
      </button>

      <div class="title-block">
        <span class="eyebrow">LLMBridge</span>
        <h1>Playground</h1>
      </div>

      <span class="status-pill {healthError ? 'status-bad' : 'status-good'}">
        {healthStatus || healthError || 'loading'}
      </span>

      <span class="status-pill subtle">{runtimeHost}:{runtimePort}</span>
    </div>

    <div class="topbar-right">
      <button type="button" class="ghost" on:click={loadExample}>Load example</button>
      <button type="button" class="ghost" on:click={loadCatalog} disabled={loadingCatalog}>
        <span class:spinning={loadingCatalog}><RefreshCw size={14} strokeWidth={1.8} /></span>
        <span>Refresh catalog</span>
      </button>
    </div>
  </header>

  <section class="summary-strip">
    <div>
      <span>Catalog</span>
      <strong>{formatMetric(catalogStats.appTokens)} app tokens · {formatMetric(catalogStats.providerKeys)} providers · {formatMetric(catalogStats.queues)} queues</strong>
    </div>
    <div>
      <span>Target</span>
      <strong>{activeProfile}</strong>
    </div>
    <div>
      <span>Route</span>
      <strong>{requestUrl}</strong>
    </div>
  </section>

  {#if catalogError}
    <section class="inline-alert error">
      <ShieldAlert size={16} strokeWidth={1.8} />
      <div>
        <strong>Catalog load failed</strong>
        <p>{catalogError}</p>
      </div>
    </section>
  {/if}

  <section class="playground-layout">
    <aside class="panel rail-panel">
      <div class="panel-head dense">
        <div>
          <span class="panel-kicker">Targets</span>
          <h2>Routing</h2>
        </div>
        <span class="panel-subtle">{formatMetric(catalogStats.recentModels)} seen</span>
      </div>

      <div class="panel-body rail-body">
        <div class="mode-switch">
          <button type="button" class:active={targetMode === 'queue'} on:click={() => (targetMode = 'queue')}>
            Queue
          </button>
          <button type="button" class:active={targetMode === 'provider-model'} on:click={() => (targetMode = 'provider-model')}>
            Provider
          </button>
          <button type="button" class:active={targetMode === 'custom'} on:click={() => (targetMode = 'custom')}>
            Custom
          </button>
        </div>

        <div class="hero-card mini-card">
          <span>Resolved model</span>
          <strong>{resolvedModel || '—'}</strong>
          <p>{activeProfile}</p>
        </div>

        <div class="mini-stack">
          <div class="mini-stack-head">
            <span>Queues</span>
            <strong>{formatMetric(queueSuggestions.length)}</strong>
          </div>
          <div class="mini-list">
            {#each queueSuggestions.slice(0, 5) as suggestion}
              <button type="button" class="mini-item" on:click={() => selectTargetPreset(suggestion)}>
                <span>queue</span>
                <strong>{suggestion}</strong>
              </button>
            {/each}
          </div>
        </div>

        <div class="mini-stack">
          <div class="mini-stack-head">
            <span>Models</span>
            <strong>{formatMetric(modelSuggestions.length)}</strong>
          </div>
          <div class="mini-list">
            {#each modelSuggestions.slice(0, 5) as suggestion}
              <button type="button" class="mini-item" on:click={() => selectTargetPreset(suggestion)}>
                <span>model</span>
                <strong>{suggestion}</strong>
              </button>
            {/each}
          </div>
        </div>
      </div>
    </aside>

    <section class="playground-center">
      <article class="panel hero-panel">
        <div class="panel-head dense">
          <div>
            <span class="panel-kicker">Playground</span>
            <h2>Chat</h2>
          </div>
          <div class="response-meta">
            <span class="meta-pill {healthError ? 'bad' : 'good'}">{healthStatus || healthError || 'loading'}</span>
            <span class="meta-pill subtle">{runtimeHost}:{runtimePort}</span>
          </div>
        </div>

        <div class="panel-body hero-grid">
          <div class="hero-copy">
            <p>Compose a message, inspect the assistant reply, and open route details only when you need them.</p>
            <div class="route-line">
              <span>Route</span>
              <strong>{requestUrl}</strong>
            </div>
          </div>

          <div class="hero-metrics">
            <div class="hero-metric">
              <span>Catalog</span>
              <strong>{formatMetric(catalogStats.appTokens)} / {formatMetric(catalogStats.providerKeys)} / {formatMetric(catalogStats.queues)}</strong>
            </div>
            <div class="hero-metric">
              <span>Target</span>
              <strong>{activeProfile}</strong>
            </div>
            <div class="hero-metric">
              <span>Protocol</span>
              <strong>{protocol}</strong>
            </div>
          </div>
        </div>
      </article>

      <article class="panel chat-panel">
        <div class="panel-head dense">
          <div>
            <span class="panel-kicker">Conversation</span>
            <h2>Latest turn</h2>
          </div>
          <div class="panel-actions">
            <span class="meta-pill {responseSummary && responseSummary.status >= 200 && responseSummary.status < 300 ? 'good' : responseSummary && responseSummary.status >= 400 ? 'bad' : 'subtle'}">
              {responseSummary ? (responseSummary.status ? `HTTP ${responseSummary.status}` : 'client error') : 'idle'}
            </span>
            <span class="meta-pill subtle">{responseSummary ? formatLatency(responseSummary.latencyMs) : '0.0 ms'}</span>
          </div>
        </div>

        <div class="panel-body chat-thread">
          {#if requestError}
            <section class="inline-alert error compact">
              <ShieldAlert size={16} strokeWidth={1.8} />
              <div>
                <strong>Request failed</strong>
                <p>{requestError}</p>
              </div>
            </section>
          {/if}

          <div class="chat-turn user-turn">
            <span class="turn-label">User</span>
            <p>{userPrompt}</p>
          </div>

          <div class="chat-turn assistant-turn">
            <span class="turn-label">Assistant</span>
            <pre>{responseSummary?.assistantText || 'Run a request to see the reply here.'}</pre>
          </div>

          {#if responseSummary?.toolCalls.length}
            <div class="chat-turn tool-turn">
              <span class="turn-label">Tools</span>
              {#each responseSummary.toolCalls as toolCall, index}
                <div class="tool-call">
                  <strong>{index + 1}. {toolCall.name}</strong>
                  <pre>{toolCall.arguments}</pre>
                </div>
              {/each}
            </div>
          {/if}

          <div class="chat-turn meta-turn">
            <span class="turn-label">Resolved</span>
            <strong>{resolvedModel || '—'}</strong>
            <p>{activeProfile}</p>
          </div>
        </div>
      </article>

      <article class="panel composer-panel">
        <div class="panel-head dense">
          <div>
            <span class="panel-kicker">Composer</span>
            <h2>Message</h2>
          </div>
          <button type="button" class="ghost compact" on:click={loadExample}>Load example</button>
        </div>

        <div class="panel-body composer-grid">
          <div class="composer-tip span-2">
            <span>Pick fast</span>
            <strong>Type the message here. Route, generation, and code live below as collapsible actions.</strong>
          </div>

          <label class="span-2">
            <span>App token</span>
            <input bind:value={appTokenValue} placeholder={DEFAULT_APP_TOKEN_PLACEHOLDER} autocomplete="off" spellcheck="false" />
          </label>

          <label class="span-2">
            <span>User prompt</span>
            <textarea bind:value={userPrompt} rows="5" spellcheck="false"></textarea>
          </label>

          <div class="action-bar span-2">
            <div class="target-preview">
              <span>Resolved model</span>
              <strong>{resolvedModel || '—'}</strong>
            </div>

            <button type="button" class="primary run-button" on:click={runRequest} disabled={requestRunning || !resolvedModel || !appTokenValue.trim()}>
              {#if requestRunning}
                <span class:spinning={requestRunning}><RefreshCw size={14} strokeWidth={1.8} /></span>
                <span>Running</span>
              {:else}
                <Sparkles size={14} strokeWidth={1.8} />
                <span>Run request</span>
              {/if}
            </button>
          </div>
        </div>
      </article>

      <section class="inspector-stack">
        <details class="panel details-panel" bind:open={showRouteSettings}>
          <summary class="details-summary">
            <div>
              <span class="panel-kicker">Actions</span>
              <strong>Route settings</strong>
            </div>
            <span>{showRouteSettings ? 'Open' : 'Closed'}</span>
          </summary>
          <div class="panel-body inspector-body">
            <div class="details-content">
              <label class="span-2">
                <span>Protocol</span>
                <select bind:value={protocol}>
                  <option value="anthropic">Anthropic</option>
                  <option value="openai">OpenAI</option>
                </select>
              </label>

              <label class="span-2">
                <span>Target mode</span>
                <select bind:value={targetMode}>
                  <option value="queue">Queue</option>
                  <option value="provider-model">Provider / model</option>
                  <option value="custom">Custom</option>
                </select>
              </label>

              {#if targetMode === 'queue'}
                <label class="span-2">
                  <span>Queue</span>
                  <input bind:value={queueName} list="queue-options" placeholder="gemini" spellcheck="false" />
                  <datalist id="queue-options">
                    {#each queueSuggestions as suggestion}
                      <option value={suggestion.replace(/^queue\//, '')}></option>
                    {/each}
                  </datalist>
                </label>
              {:else if targetMode === 'provider-model'}
                <label>
                  <span>Provider</span>
                  <input bind:value={provider} list="provider-options" placeholder="google" spellcheck="false" />
                  <datalist id="provider-options">
                    {#each providerSuggestions as suggestion}
                      <option value={suggestion}></option>
                    {/each}
                  </datalist>
                </label>

                <label>
                  <span>Model</span>
                  <input bind:value={model} list="model-options" placeholder="gemini-3.1-flash" spellcheck="false" />
                  <datalist id="model-options">
                    {#each modelSuggestions as suggestion}
                      <option value={suggestion}></option>
                    {/each}
                  </datalist>
                </label>
              {:else}
                <label class="span-2">
                  <span>Custom model</span>
                  <input bind:value={customModel} placeholder="queue/gemini or google/gemini-3.1-flash" spellcheck="false" />
                </label>
              {/if}

              <div class="preset-strip span-2">
                <div class="preset-strip-head">
                  <span>Suggestions</span>
                  <strong>{targetMode === 'queue' ? 'Queues' : targetMode === 'provider-model' ? 'Providers / models' : 'All targets'}</strong>
                </div>
                <div class="preset-chips">
                  {#if targetMode === 'queue' || targetMode === 'custom'}
                    {#each queueSuggestions.slice(0, 4) as suggestion}
                      <button type="button" class="preset-chip" on:click={() => selectTargetPreset(suggestion)}>
                        {suggestion.replace(/^queue\//, '')}
                      </button>
                    {/each}
                  {/if}
                  {#if targetMode === 'provider-model' || targetMode === 'custom'}
                    {#each providerSuggestions.slice(0, 3) as providerSuggestion}
                      {#each modelSuggestions.slice(0, 3) as modelSuggestion}
                        <button
                          type="button"
                          class="preset-chip"
                          on:click={() => selectTargetPreset(`${providerSuggestion}/${modelSuggestion}`)}
                        >
                          {providerSuggestion}/{modelSuggestion}
                        </button>
                      {/each}
                    {/each}
                  {/if}
                </div>
              </div>
            </div>
          </div>
        </details>

        <details class="panel details-panel" bind:open={showGenerationSettings}>
          <summary class="details-summary">
            <div>
              <span class="panel-kicker">Actions</span>
              <strong>Generation and tools</strong>
            </div>
            <span>{showGenerationSettings ? 'Open' : 'Closed'}</span>
          </summary>
          <div class="panel-body inspector-body">
            <div class="details-content">
              <label class="span-2">
                <span>System prompt</span>
                <textarea bind:value={systemPrompt} rows="5" spellcheck="false"></textarea>
              </label>
              <div class="settings-grid two">
                <label>
                  <span>Temperature</span>
                  <input type="number" step="0.1" min="0" max="2" bind:value={temperature} />
                </label>
                <label>
                  <span>Max tokens</span>
                  <input type="number" step="1" min="1" bind:value={maxTokens} />
                </label>
                <label>
                  <span>Top p</span>
                  <input type="number" step="0.1" min="0" max="1" bind:value={topP} />
                </label>
              </div>
              <label class="toggle-row">
                <input type="checkbox" bind:checked={toolCallingEnabled} />
                <span>Tool calling sample</span>
              </label>
              <p class="muted-copy">Keep this closed if you only want to test the route. Open it when you need to tune the generated request.</p>
            </div>
          </div>
        </details>

        <details class="panel details-panel" bind:open={showRequestCode}>
          <summary class="details-summary">
            <div>
              <span class="panel-kicker">Actions</span>
              <strong>Request code</strong>
            </div>
            <span>{showRequestCode ? 'Open' : 'Closed'}</span>
          </summary>
          <div class="panel-body inspector-body">
            <div class="panel-actions code-actions">
              <div class="tab-strip">
                <button type="button" class:active={codeTab === 'curl'} on:click={() => (codeTab = 'curl')}>cURL</button>
                <button type="button" class:active={codeTab === 'json'} on:click={() => (codeTab = 'json')}>JSON</button>
                <button type="button" class:active={codeTab === 'js'} on:click={() => (codeTab = 'js')}>JS</button>
              </div>
              <button type="button" class="ghost compact" on:click={() => copyText(codeTab === 'curl' ? curlSnippet : codeTab === 'js' ? jsSnippet : jsonSnippet)}>
                {#if copiedSnippet === (codeTab === 'curl' ? curlSnippet : codeTab === 'js' ? jsSnippet : jsonSnippet)}
                  <Check size={14} strokeWidth={2} />
                {:else}
                  <Copy size={14} strokeWidth={1.8} />
                {/if}
                <span>Copy</span>
              </button>
            </div>
            <div class="code-hint">
              <span>Route</span>
              <strong>{requestUrl}</strong>
            </div>
            <pre><code>{codeTab === 'curl' ? curlSnippet : codeTab === 'js' ? jsSnippet : jsonSnippet}</code></pre>
          </div>
        </details>

        <details class="panel details-panel" bind:open={showRawResponse}>
          <summary class="details-summary">
            <div>
              <span class="panel-kicker">Actions</span>
              <strong>Raw response</strong>
            </div>
            <span>{showRawResponse ? 'Open' : 'Closed'}</span>
          </summary>
          <div class="panel-body inspector-body">
            <div class="details-content">
              <div class="settings-grid two">
                <div class="mini-stat">
                  <span>Status</span>
                  <strong>{responseSummary ? (responseSummary.status ? `HTTP ${responseSummary.status}` : 'client error') : 'idle'}</strong>
                </div>
                <div class="mini-stat">
                  <span>Latency</span>
                  <strong>{responseSummary ? formatLatency(responseSummary.latencyMs) : '0.0 ms'}</strong>
                </div>
              </div>
              <div class="section-card">
                <div class="section-label">Headers</div>
                <pre>{responseSummary?.headers.map(([key, value]) => `${key}: ${value}`).join('\n') || 'No headers yet.'}</pre>
              </div>
              <div class="section-card">
                <div class="section-label">Body</div>
                <pre>{responseSummary ? formatBodyText(responseSummary.body) : 'No response yet.'}</pre>
              </div>
            </div>
          </div>
        </details>
      </section>
    </section>
  </section>
</main>

<style>
  :global(body) {
    background:
      radial-gradient(circle at top, rgba(216, 184, 88, 0.05), transparent 30%),
      linear-gradient(180deg, #0b0d11 0%, #0d1116 55%, #0b0d11 100%);
  }

  .playground-shell {
    min-height: 100vh;
    padding: 0;
    color: var(--text);
    background: transparent;
  }

  .playground-topbar,
  .summary-strip,
  .panel {
    border: 1px solid var(--border);
    border-radius: 5px;
    background: var(--panel);
  }

  .playground-topbar {
    margin: 1rem 1rem 0;
    min-height: 56px;
    padding: 0.75rem 1rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    backdrop-filter: blur(14px);
  }

  .topbar-left {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    min-width: 0;
    flex-wrap: wrap;
  }

  .back-button {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    height: 32px;
    padding: 0 0.8rem;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: rgba(255, 255, 255, 0.02);
    color: var(--text);
    font-size: 0.8rem;
  }

  .title-block {
    display: grid;
    gap: 0.05rem;
  }

  .eyebrow {
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--accent);
    font-size: 0.62rem;
    font-weight: 700;
  }

  .title-block h1 {
    margin: 0;
    font-size: 1rem;
    font-weight: 500;
    line-height: 1.2;
  }

  .status-pill,
  .meta-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    height: 28px;
    padding: 0 0.6rem;
    border: 1px solid var(--border);
    border-radius: 4px;
    font-size: 0.7rem;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
    background: rgba(255, 255, 255, 0.02);
  }

  .status-good,
  .meta-pill.good {
    color: #b7c98f;
    border-color: rgba(138, 168, 106, 0.3);
    background: rgba(138, 168, 106, 0.12);
  }

  .status-bad,
  .meta-pill.bad {
    color: #f0b3b3;
    border-color: rgba(200, 117, 117, 0.3);
    background: rgba(200, 117, 117, 0.12);
  }

  .status-pill.subtle,
  .meta-pill.subtle {
    background: rgba(255, 255, 255, 0.02);
  }

  .topbar-right {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .ghost {
    height: 32px;
    padding: 0 0.8rem;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: transparent;
    color: var(--text);
    font-size: 0.8rem;
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
  }

  .summary-strip {
    margin: 1rem 1rem 0;
    padding: 0.8rem 1rem;
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.75rem;
  }

  .summary-strip div {
    display: grid;
    gap: 0.15rem;
  }

  .summary-strip span,
  .panel-kicker,
  .section-label {
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: 0.65rem;
    color: var(--muted);
  }

  .summary-strip strong {
    font-size: 0.85rem;
    font-weight: 500;
    color: var(--text);
    word-break: break-word;
  }

  .inline-alert {
    margin: 1rem 1rem 0;
    padding: 0.9rem 1rem;
    display: flex;
    align-items: flex-start;
    gap: 0.75rem;
    border: 1px solid rgba(200, 117, 117, 0.32);
    background: rgba(200, 117, 117, 0.08);
    border-radius: 5px;
  }

  .inline-alert.compact {
    margin: 0 0 1rem;
  }

  .inline-alert p {
    margin: 0.15rem 0 0;
    color: rgba(255, 225, 225, 0.85);
    font-size: 0.82rem;
  }

  .panel-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.9rem 1rem;
    border-bottom: 1px solid var(--border);
  }

  .panel-head.dense {
    padding: 0.8rem 1rem;
  }

  .panel-head h2 {
    margin: 0.15rem 0 0;
    font-size: 0.96rem;
    font-weight: 500;
  }

  .panel-subtle {
    font-size: 0.72rem;
    color: var(--muted);
  }

  .panel-body {
    padding: 1rem;
  }

  label {
    display: grid;
    gap: 0.35rem;
    font-size: 0.8rem;
    color: var(--text);
  }

  label span {
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: 0.63rem;
  }

  input,
  select,
  textarea {
    width: 100%;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: rgba(255, 255, 255, 0.03);
    color: var(--text);
    padding: 0.55rem 0.7rem;
    font: inherit;
    outline: none;
  }

  textarea {
    resize: vertical;
    min-height: 96px;
    line-height: 1.4;
  }

  input:focus,
  select:focus,
  textarea:focus {
    border-color: rgba(216, 184, 88, 0.65);
    box-shadow: 0 0 0 2px rgba(216, 184, 88, 0.12);
  }

  .toggle-row {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding-top: 0.2rem;
  }

  .toggle-row input {
    width: 16px;
    height: 16px;
    margin: 0;
    padding: 0;
    accent-color: var(--accent);
  }

  .toggle-row span {
    text-transform: none;
    letter-spacing: 0;
    font-size: 0.84rem;
    color: var(--text);
  }

  .target-preview {
    padding: 0.8rem 0.9rem;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: rgba(255, 255, 255, 0.02);
    display: grid;
    gap: 0.15rem;
  }

  .target-preview span {
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
    font-size: 0.63rem;
  }

  .target-preview strong {
    font-size: 0.9rem;
    font-weight: 500;
    word-break: break-word;
  }

  .run-button {
    height: 38px;
    justify-content: center;
    background: rgba(216, 184, 88, 0.12);
    border-color: rgba(216, 184, 88, 0.35);
    color: #ead48f;
  }

  .run-button:hover:not(:disabled) {
    background: rgba(216, 184, 88, 0.18);
    border-color: rgba(216, 184, 88, 0.45);
  }

  .panel {
    overflow: hidden;
  }

  .panel-actions {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    flex-wrap: wrap;
    justify-content: flex-end;
  }

  .tab-strip {
    display: inline-flex;
    border: 1px solid var(--border);
    border-radius: 5px;
    overflow: hidden;
    background: rgba(255, 255, 255, 0.02);
  }

  .tab-strip button {
    height: 30px;
    padding: 0 0.8rem;
    border: 0;
    border-right: 1px solid var(--border);
    border-radius: 0;
    background: transparent;
    color: var(--muted);
    font-size: 0.75rem;
  }

  .tab-strip button:last-child {
    border-right: 0;
  }

  .tab-strip button.active {
    background: rgba(255, 255, 255, 0.06);
    color: var(--text);
  }

  .ghost.compact {
    height: 30px;
    padding: 0 0.75rem;
  }

  .code-hint {
    display: grid;
    gap: 0.25rem;
    padding: 0.8rem 0.85rem;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: rgba(255, 255, 255, 0.02);
  }

  .code-hint span {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
  }

  .code-hint strong {
    font-size: 0.88rem;
    color: var(--text);
    word-break: break-all;
  }

  .response-meta {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .chat-panel,
  .details-panel {
    backdrop-filter: blur(14px);
  }

  .chat-panel {
    order: 2;
  }

  .chat-panel .panel-body {
    padding: 1rem;
  }

  .chat-thread {
    display: grid;
    gap: 0.75rem;
  }

  .chat-turn {
    display: grid;
    gap: 0.4rem;
    padding: 0.9rem 0.95rem;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.02);
  }

  .chat-turn.user-turn {
    margin-left: auto;
    width: min(100%, 88%);
    background: rgba(216, 184, 88, 0.06);
    border-color: rgba(216, 184, 88, 0.16);
  }

  .chat-turn.assistant-turn {
    width: min(100%, 96%);
  }

  .chat-turn.tool-turn,
  .chat-turn.meta-turn {
    width: min(100%, 96%);
    background: rgba(255, 255, 255, 0.015);
  }

  .turn-label {
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--muted);
  }

  .chat-turn p,
  .chat-turn pre {
    margin: 0;
    white-space: pre-wrap;
    word-break: break-word;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
    font-size: 0.84rem;
    line-height: 1.55;
    color: #dbe3ee;
  }

  .chat-turn.meta-turn strong {
    font-size: 0.92rem;
    color: var(--text);
  }

  .chat-turn.meta-turn p {
    font-family: inherit;
    color: var(--muted);
  }

  .tool-call {
    display: grid;
    gap: 0.45rem;
    padding: 0.85rem 0.9rem;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: rgba(255, 255, 255, 0.02);
  }

  .tool-call pre {
    max-height: 220px;
    overflow: auto;
  }

  .spinning {
    animation: spin 1s linear infinite;
  }

  @keyframes spin {
    from {
      transform: rotate(0deg);
    }
    to {
      transform: rotate(360deg);
    }
  }

  .playground-layout {
    display: grid;
    grid-template-columns: 220px minmax(0, 1fr);
    gap: 0.85rem;
    padding: 0.85rem 1rem 1rem;
    align-items: start;
  }

  .rail-panel,
  .hero-panel,
  .composer-panel,
  .chat-panel,
  .details-panel {
    backdrop-filter: blur(14px);
  }

  .rail-panel {
    position: sticky;
    top: 0.85rem;
  }

  .rail-body,
  .hero-grid,
  .composer-grid {
    display: grid;
    gap: 0.85rem;
  }

  .rail-body {
    padding: 0.9rem;
    position: sticky;
    top: 4.4rem;
  }

  .mode-switch {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.35rem;
  }

  .mode-switch button {
    min-height: 38px;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: rgba(255, 255, 255, 0.02);
    color: var(--muted);
    font-weight: 600;
  }

  .mode-switch button.active {
    border-color: rgba(216, 184, 88, 0.45);
    background: rgba(216, 184, 88, 0.08);
    color: var(--text);
  }

  .mini-card,
  .section-card,
  .hero-metric,
  .mini-item {
    border: 1px solid var(--border);
    border-radius: 5px;
    background: rgba(255, 255, 255, 0.02);
  }

  .hero-card {
    display: grid;
    gap: 0.35rem;
    padding: 0.9rem;
  }

  .hero-card span,
  .hero-metric span,
  .mini-stack-head span {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--muted);
  }

  .hero-card strong,
  .hero-metric strong {
    font-size: 0.95rem;
    color: var(--text);
    word-break: break-word;
  }

  .hero-card p {
    margin: 0;
    color: var(--muted);
    font-size: 0.82rem;
  }

  .mini-stack {
    display: grid;
    gap: 0.6rem;
  }

  .mini-stack-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.75rem;
    padding: 0 0.1rem;
  }

  .mini-list {
    display: grid;
    gap: 0.35rem;
  }

  .mini-item {
    display: grid;
    gap: 0.15rem;
    padding: 0.7rem 0.75rem;
    text-align: left;
    color: var(--text);
  }

  .mini-item span {
    font-size: 0.72rem;
    color: var(--muted);
  }

  .mini-item strong {
    font-size: 0.84rem;
    font-weight: 600;
    word-break: break-word;
  }

  .playground-center {
    display: flex;
    flex-direction: column;
    gap: 0.85rem;
    min-width: 0;
    min-height: 100%;
  }

  .hero-panel .panel-body {
    padding: 1rem;
  }

  .hero-grid {
    grid-template-columns: minmax(0, 1.35fr) minmax(220px, 0.75fr);
  }

  .hero-copy {
    display: grid;
    gap: 0.9rem;
    align-content: start;
  }

  .hero-copy p {
    margin: 0;
    color: var(--text);
    font-size: 1rem;
    line-height: 1.5;
    max-width: 60ch;
  }

  .route-line {
    display: grid;
    gap: 0.35rem;
    padding: 0.85rem 0.9rem;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: rgba(255, 255, 255, 0.02);
  }

  .route-line span {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--muted);
  }

  .route-line strong {
    font-size: 0.92rem;
    word-break: break-all;
  }

  .hero-metrics {
    display: grid;
    gap: 0.55rem;
    align-content: start;
  }

  .hero-metric {
    padding: 0.8rem 0.85rem;
    display: grid;
    gap: 0.25rem;
    min-height: 74px;
  }

  .composer-panel .panel-body {
    padding: 1rem;
  }

  .hero-panel {
    order: 1;
  }

  .composer-panel {
    order: 3;
    position: sticky;
    bottom: 0.85rem;
    z-index: 2;
  }

  .composer-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .composer-tip {
    display: grid;
    gap: 0.25rem;
    padding: 0.85rem 0.9rem;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: rgba(255, 255, 255, 0.02);
  }

  .composer-tip span,
  .preset-strip-head span {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
  }

  .composer-tip strong {
    font-size: 0.88rem;
    color: var(--text);
    line-height: 1.45;
  }

  .preset-strip {
    display: grid;
    gap: 0.6rem;
    padding: 0.85rem 0.9rem;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: rgba(255, 255, 255, 0.02);
  }

  .preset-strip-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.75rem;
  }

  .preset-strip-head strong {
    font-size: 0.82rem;
    color: var(--text);
  }

  .preset-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem;
  }

  .preset-chip {
    height: 30px;
    padding: 0 0.75rem;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: rgba(255, 255, 255, 0.02);
    color: var(--text);
    font-size: 0.78rem;
  }

  .preset-chip:hover:not(:disabled) {
    background: rgba(216, 184, 88, 0.08);
    border-color: rgba(216, 184, 88, 0.3);
  }

  .span-2 {
    grid-column: 1 / -1;
  }

  .action-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.75rem;
  }

  .action-bar .target-preview {
    min-width: 0;
    flex: 1;
  }

  .section-card {
    display: grid;
    gap: 0.6rem;
    padding: 0.85rem;
  }

  .section-card pre {
    max-height: 220px;
    overflow: auto;
  }

  .settings-grid {
    display: grid;
    gap: 0.65rem;
  }

  .settings-grid.two {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .settings-grid label {
    display: grid;
    gap: 0.35rem;
  }

  .settings-grid span,
  .target-preview span {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
  }

  .settings-grid input {
    width: 100%;
  }

  .inspector-stack {
    display: grid;
    gap: 0.85rem;
    order: 4;
  }

  .details-panel {
    overflow: hidden;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: var(--panel);
  }

  .details-summary {
    list-style: none;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    padding: 0.85rem 1rem;
    cursor: pointer;
  }

  .details-summary::-webkit-details-marker {
    display: none;
  }

  .details-summary > div {
    display: grid;
    gap: 0.08rem;
  }

  .details-summary strong {
    font-size: 0.92rem;
    color: var(--text);
  }

  .details-summary span:last-child {
    color: var(--muted);
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }

  .inspector-body {
    padding: 0 1rem 1rem;
  }

  .code-actions {
    margin-bottom: 0.65rem;
  }

  .details-content {
    display: grid;
    gap: 0.9rem;
  }

  .mini-stat {
    display: grid;
    gap: 0.25rem;
    padding: 0.8rem 0.85rem;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: rgba(255, 255, 255, 0.02);
  }

  .mini-stat span {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
  }

  .mini-stat strong {
    font-size: 0.9rem;
    color: var(--text);
  }

  .details-panel summary {
    background: transparent;
  }

  @media (max-width: 1280px) {
    .playground-layout {
      grid-template-columns: 1fr;
    }

    .rail-panel {
      position: static;
    }

    .hero-grid {
      grid-template-columns: 1fr;
    }

    .composer-panel {
      position: static;
    }
  }

  @media (max-width: 760px) {
    .playground-layout {
      padding-left: 0.5rem;
      padding-right: 0.5rem;
    }

    .composer-grid {
      grid-template-columns: 1fr;
    }

    .span-2 {
      grid-column: auto;
    }

    .action-bar {
      flex-direction: column;
      align-items: stretch;
    }

    .mode-switch {
      grid-template-columns: 1fr;
    }
  }
</style>
