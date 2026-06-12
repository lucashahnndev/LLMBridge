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
  import { topbarTitle } from '$lib/stores';

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
  let activeOutputTab: 'reply' | 'code' | 'raw' = 'reply';

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
    activeOutputTab = 'reply';
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
    activeOutputTab = 'reply';
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
    topbarTitle.set('Playground');
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

<div class="playground-page-overlay">
  {#if catalogError}
    <section class="inline-alert error" style="position: absolute; top: 1rem; right: 1rem; z-index: 100; max-width: 400px; box-shadow: 0 4px 12px rgba(0,0,0,0.5);">
      <ShieldAlert size={16} strokeWidth={1.8} />
      <div>
        <strong>Catalog load failed</strong>
        <p>{catalogError}</p>
      </div>
    </section>
  {/if}

  <!-- Left Side: Composer and Settings -->
  <aside class="composer-sidebar">
    <div class="sidebar-header" style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.85rem; border-bottom: 1px solid var(--border); padding-bottom: 0.5rem; flex-shrink: 0;">
      <span style="font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted);">Composer</span>
      <button type="button" class="preset-chip" style="margin: 0; padding: 0.15rem 0.45rem; font-size: 0.7rem; border-radius: 4px; height: auto;" on:click={loadExample}>Load example</button>
    </div>
      <!-- Target Mode & Protocol selection -->
      <div class="sidebar-section">
        <div class="section-title">Routing & Protocol</div>
        <div class="input-grid">
          <label>
            <span>Protocol</span>
            <select bind:value={protocol}>
              <option value="anthropic">Anthropic</option>
              <option value="openai">OpenAI</option>
            </select>
          </label>
          
          <label>
            <span>Target Mode</span>
            <select bind:value={targetMode}>
              <option value="queue">Queue</option>
              <option value="provider-model">Provider / Model</option>
              <option value="custom">Custom</option>
            </select>
          </label>
        </div>

        {#if targetMode === 'queue'}
          <label class="field-margin">
            <span>Queue Name</span>
            <input bind:value={queueName} list="queue-options" placeholder="gemini" spellcheck="false" />
            <datalist id="queue-options">
              {#each queueSuggestions as suggestion}
                <option value={suggestion.replace(/^queue\//, '')}></option>
              {/each}
            </datalist>
          </label>
        {:else if targetMode === 'provider-model'}
          <div class="input-grid field-margin">
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
          </div>
        {:else}
          <label class="field-margin">
            <span>Custom Target</span>
            <input bind:value={customModel} placeholder="queue/gemini" spellcheck="false" />
          </label>
        {/if}

        <!-- Suggestion Chips inside Sidebar -->
        <div class="preset-strip field-margin">
          <div class="preset-strip-head">
            <span>Suggestions</span>
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
              {#each providerSuggestions.slice(0, 2) as providerSuggestion}
                {#each modelSuggestions.slice(0, 2) as modelSuggestion}
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

      <!-- App Token -->
      <div class="sidebar-section">
        <label>
          <span>App Token</span>
          <input bind:value={appTokenValue} type="password" placeholder="lk-key-..." autocomplete="off" spellcheck="false" />
        </label>
      </div>

      <!-- Parameters Collapsible -->
      <details class="sidebar-section-details" bind:open={showGenerationSettings}>
        <summary class="details-header">
          <span>Parameters & System</span>
          <span class="icon-indicator">{showGenerationSettings ? 'Collapse' : 'Expand'}</span>
        </summary>
        <div class="details-body">
          <label class="field-margin">
            <span>System Prompt</span>
            <textarea bind:value={systemPrompt} rows="3" placeholder="System instructions..." spellcheck="false"></textarea>
          </label>
          
          <div class="input-grid field-margin">
            <label>
              <span>Temperature</span>
              <input type="number" step="0.1" min="0" max="2" bind:value={temperature} />
            </label>
            <label>
              <span>Max Tokens</span>
              <input type="number" step="1" min="1" bind:value={maxTokens} />
            </label>
            <label>
              <span>Top P</span>
              <input type="number" step="0.1" min="0" max="1" bind:value={topP} />
            </label>
          </div>

          <label class="toggle-row field-margin">
            <input type="checkbox" bind:checked={toolCallingEnabled} />
            <span>Enable tool calling sample</span>
          </label>
        </div>
      </details>

      <!-- Composer Input Area -->
      <div class="composer-prompt-area">
        <label>
          <span>User Message</span>
          <textarea bind:value={userPrompt} rows="6" placeholder="Type a message to prompt the gateway..." spellcheck="false"></textarea>
        </label>
        
        <div class="composer-actions">
          <div class="resolved-badge">
            <span class="badge-label">Resolved Target:</span>
            <strong class="badge-value">{resolvedModel || '—'}</strong>
          </div>

          <button type="button" class="primary-run-btn" on:click={runRequest} disabled={requestRunning || !resolvedModel || !appTokenValue.trim()}>
            {#if requestRunning}
              <span class="spinning-icon"><RefreshCw size={14} strokeWidth={1.8} /></span>
              <span>Running...</span>
            {:else}
              <Sparkles size={14} strokeWidth={1.8} />
              <span>Run Request</span>
            {/if}
          </button>
        </div>
      </div>
    </aside>

    <!-- Right Side: Outputs & Inspector tabbed view -->
    <section class="inspector-output-pane">
      <div class="pane-tabs-header">
        <div class="tabs-buttons">
          <button class:active={activeOutputTab === 'reply'} on:click={() => activeOutputTab = 'reply'}>
            Chat Reply
          </button>
          <button class:active={activeOutputTab === 'code'} on:click={() => activeOutputTab = 'code'}>
            Code Snippets
          </button>
          <button class:active={activeOutputTab === 'raw'} on:click={() => activeOutputTab = 'raw'}>
            Raw Details
          </button>
        </div>

        {#if responseSummary}
          <div class="pane-metrics">
            <span class="status-badge {responseSummary.status >= 200 && responseSummary.status < 300 ? 'status-ok' : 'status-err'}">
              HTTP {responseSummary.status}
            </span>
            <span class="latency-badge">
              {formatLatency(responseSummary.latencyMs)}
            </span>
          </div>
        {/if}
      </div>

      <div class="pane-content-wrapper">
        {#if activeOutputTab === 'reply'}
          <div class="tab-content chat-view">
            {#if requestError}
              <div class="error-banner">
                <ShieldAlert size={16} strokeWidth={1.8} />
                <div>
                  <strong>Request Failed</strong>
                  <p>{requestError}</p>
                </div>
              </div>
            {/if}

            {#if !responseSummary && !requestRunning && !requestError}
              <div class="empty-state">
                <Sparkles size={24} strokeWidth={1.2} />
                <h3>Playground Ready</h3>
                <p>Type a message in the composer on the left and click **Run Request** to test gateway routing, keys, and latency.</p>
              </div>
            {:else}
              <!-- User Prompt Card -->
              <div class="chat-message user-msg">
                <div class="msg-header">USER</div>
                <div class="msg-body">{userPrompt}</div>
              </div>

              <!-- Assistant Response Card -->
              <div class="chat-message assistant-msg {requestRunning ? 'shimmer' : ''}">
                <div class="msg-header">ASSISTANT</div>
                <div class="msg-body">
                  {#if requestRunning}
                    <div class="loading-placeholder">Waiting for gateway response...</div>
                  {:else}
                    <pre class="assistant-pre">{responseSummary?.assistantText || 'No reply text returned.'}</pre>
                  {/if}
                </div>
              </div>

              <!-- Tool Calls Card -->
              {#if responseSummary?.toolCalls.length}
                <div class="chat-message tool-msg">
                  <div class="msg-header">TOOL CALLS</div>
                  <div class="msg-body">
                    {#each responseSummary.toolCalls as toolCall, index}
                      <div class="tool-call-block">
                        <strong>{index + 1}. {toolCall.name}</strong>
                        <pre>{toolCall.arguments}</pre>
                      </div>
                    {/each}
                  </div>
                </div>
              {/if}
            {/if}
          </div>
        {:else if activeOutputTab === 'code'}
          <div class="tab-content code-view">
            <div class="code-sub-tabs">
              <div class="sub-tab-buttons">
                <button class:active={codeTab === 'curl'} on:click={() => codeTab = 'curl'}>cURL</button>
                <button class:active={codeTab === 'js'} on:click={() => codeTab = 'js'}>JavaScript</button>
                <button class:active={codeTab === 'json'} on:click={() => codeTab = 'json'}>JSON Payload</button>
              </div>

              <button type="button" class="copy-btn" on:click={() => copyText(codeTab === 'curl' ? curlSnippet : codeTab === 'js' ? jsSnippet : jsonSnippet)}>
                {#if copiedSnippet === (codeTab === 'curl' ? curlSnippet : codeTab === 'js' ? jsSnippet : jsonSnippet)}
                  <Check size={14} strokeWidth={2} />
                  <span>Copied!</span>
                {:else}
                  <Copy size={14} strokeWidth={1.8} />
                  <span>Copy</span>
                {/if}
              </button>
            </div>

            <div class="code-output-block">
              <div class="code-header">
                <span>Endpoint:</span>
                <strong>{requestUrl}</strong>
              </div>
              <pre class="code-pre"><code>{codeTab === 'curl' ? curlSnippet : codeTab === 'js' ? jsSnippet : jsonSnippet}</code></pre>
            </div>
          </div>
        {:else if activeOutputTab === 'raw'}
          <div class="tab-content raw-view">
            {#if !responseSummary}
              <div class="empty-state">
                <h3>No Response Details</h3>
                <p>Run a request first to inspect response headers and raw payload details.</p>
              </div>
            {:else}
              <div class="raw-section">
                <div class="raw-title">Response Headers</div>
                <pre class="raw-headers-pre">{responseSummary.headers.map(([key, val]) => `${key}: ${val}`).join('\n') || 'No headers returned.'}</pre>
              </div>

              <div class="raw-section">
                <div class="raw-title">Response Body</div>
                <pre class="raw-body-pre">{formatBodyText(responseSummary.body)}</pre>
              </div>
            {/if}
          </div>
        {/if}
      </div>
    </section>
  </div>

<style>
  :global(body) {
    background:
      radial-gradient(circle at top, rgba(216, 184, 88, 0.05), transparent 30%),
      linear-gradient(180deg, #0b0d11 0%, #0d1116 55%, #0b0d11 100%);
  }

  .playground-page-overlay {
    position: absolute;
    inset: 0;
    z-index: 10;
    display: grid;
    grid-template-columns: 420px 1fr;
    background: var(--bg);
    color: var(--text);
    overflow: hidden;
  }

  /* Left Side: Sidebar/Composer */
  .composer-sidebar {
    display: flex;
    flex-direction: column;
    border-right: 1px solid var(--border);
    background: rgba(13, 17, 22, 0.35);
    overflow-y: auto;
    padding: 1.25rem;
    gap: 1.25rem;
  }

  .sidebar-section {
    display: flex;
    flex-direction: column;
    padding: 1rem;
    border: 1px solid var(--border);
    background: rgba(255, 255, 255, 0.015);
    border-radius: 6px;
  }

  .section-title {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
    margin-bottom: 0.85rem;
  }

  .input-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.85rem;
  }

  .field-margin {
    margin-top: 0.85rem;
  }

  label {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }

  label span {
    font-size: 0.68rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--muted);
  }

  input, select, textarea {
    background: rgba(255, 255, 255, 0.03);
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 4px;
    padding: 0.5rem 0.65rem;
    font-size: 0.82rem;
    font-family: inherit;
    outline: none;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
  }

  input:focus, select:focus, textarea:focus {
    border-color: rgba(216, 184, 88, 0.55);
    box-shadow: 0 0 0 2px rgba(216, 184, 88, 0.08);
  }

  textarea {
    resize: none;
    line-height: 1.45;
  }

  /* Preset strip / suggestion chips */
  .preset-strip {
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
  }

  .preset-strip-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .preset-strip-head span {
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
  }

  .preset-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
  }

  .preset-chip {
    padding: 0.2rem 0.5rem;
    background: rgba(255, 255, 255, 0.02);
    border: 1px solid var(--border);
    border-radius: 4px;
    color: var(--text);
    font-size: 0.72rem;
    cursor: pointer;
    transition: background 0.15s ease, border-color 0.15s ease;
  }

  .preset-chip:hover {
    background: rgba(216, 184, 88, 0.06);
    border-color: rgba(216, 184, 88, 0.3);
  }

  /* Collapsible Settings details styling */
  .sidebar-section-details {
    border: 1px solid var(--border);
    background: rgba(255, 255, 255, 0.015);
    border-radius: 6px;
    overflow: hidden;
  }

  .details-header {
    padding: 0.85rem 1rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    cursor: pointer;
    user-select: none;
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
  }

  .details-header::-webkit-details-marker {
    display: none;
  }

  .icon-indicator {
    font-size: 0.65rem;
    color: var(--muted);
  }

  .details-body {
    padding: 0 1rem 1rem;
    border-top: 1px dashed var(--border);
    padding-top: 1rem;
  }

  .toggle-row {
    flex-direction: row;
    align-items: center;
    gap: 0.5rem;
    cursor: pointer;
  }

  .toggle-row input[type="checkbox"] {
    width: 14px;
    height: 14px;
    cursor: pointer;
    accent-color: var(--accent);
  }

  .toggle-row span {
    font-size: 0.75rem;
    color: var(--text);
    text-transform: none;
    letter-spacing: 0;
  }

  /* Composer Message & Run */
  .composer-prompt-area {
    display: flex;
    flex-direction: column;
    gap: 0.85rem;
    margin-top: auto;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
  }

  .composer-actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
  }

  .resolved-badge {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .resolved-badge .badge-label {
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
  }

  .resolved-badge .badge-value {
    font-size: 0.85rem;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .primary-run-btn {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    height: 36px;
    padding: 0 1rem;
    background: #ead48f;
    color: #111;
    border: none;
    border-radius: 4px;
    font-weight: 600;
    font-size: 0.8rem;
    cursor: pointer;
    flex-shrink: 0;
    transition: opacity 0.15s ease;
  }

  .primary-run-btn:hover:not(:disabled) {
    opacity: 0.9;
  }

  .primary-run-btn:disabled {
    background: rgba(255, 255, 255, 0.05);
    color: var(--muted);
    border: 1px solid var(--border);
    cursor: not-allowed;
  }

  /* Right Side: Tabbed output details pane */
  .inspector-output-pane {
    display: flex;
    flex-direction: column;
    min-height: 0;
    background: rgba(11, 13, 17, 0.85);
  }

  .pane-tabs-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 48px;
    padding: 0 1.25rem;
    border-bottom: 1px solid var(--border);
    background: rgba(13, 17, 22, 0.45);
    flex-shrink: 0;
  }

  .tabs-buttons {
    display: flex;
    gap: 0.5rem;
    height: 100%;
    align-items: center;
  }

  .tabs-buttons button {
    height: 100%;
    padding: 0 0.85rem;
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--muted);
    font-size: 0.82rem;
    font-weight: 500;
    cursor: pointer;
    transition: color 0.15s ease, border-color 0.15s ease;
  }

  .tabs-buttons button:hover {
    color: var(--text);
  }

  .tabs-buttons button.active {
    color: var(--text);
    border-bottom-color: rgba(216, 184, 88, 0.85);
  }

  .pane-metrics {
    display: flex;
    align-items: center;
    gap: 0.65rem;
  }

  .status-badge {
    padding: 0.15rem 0.45rem;
    font-size: 0.72rem;
    font-weight: 600;
    border-radius: 4px;
    border: 1px solid transparent;
  }

  .status-badge.status-ok {
    color: #4cd964;
    border-color: rgba(76, 217, 100, 0.2);
    background: rgba(76, 217, 100, 0.06);
  }

  .status-badge.status-err {
    color: #ff3b30;
    border-color: rgba(255, 59, 48, 0.2);
    background: rgba(255, 59, 48, 0.06);
  }

  .latency-badge {
    color: var(--muted);
    font-size: 0.75rem;
    font-weight: 500;
  }

  .pane-content-wrapper {
    flex: 1;
    overflow-y: auto;
    padding: 1.5rem;
    min-height: 0;
  }

  .tab-content {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
    min-height: 100%;
  }

  /* Empty state */
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    flex: 1;
    gap: 0.5rem;
    padding: 3rem 1rem;
    color: var(--muted);
  }

  .empty-state h3 {
    margin: 0;
    font-size: 1rem;
    font-weight: 600;
    color: var(--text);
  }

  .empty-state p {
    margin: 0;
    font-size: 0.82rem;
    max-width: 44ch;
    line-height: 1.45;
  }

  /* Chat view reply style */
  .chat-view {
    justify-content: flex-start;
  }

  .chat-message {
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.015);
    padding: 1rem;
  }

  .chat-message.user-msg {
    border-left: 2px solid var(--muted);
  }

  .chat-message.assistant-msg {
    border-left: 2px solid rgba(216, 184, 88, 0.65);
    background: rgba(216, 184, 88, 0.01);
  }

  .chat-message.tool-msg {
    border-left: 2px solid #5856d6;
  }

  .msg-header {
    font-size: 0.65rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
  }

  .msg-body {
    font-size: 0.88rem;
    line-height: 1.5;
    color: var(--text);
  }

  .assistant-pre {
    margin: 0;
    white-space: pre-wrap;
    font-family: var(--font-mono, monospace);
    font-size: 0.85rem;
  }

  .tool-call-block {
    padding: 0.65rem;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: rgba(0, 0, 0, 0.2);
    margin-top: 0.5rem;
  }

  .tool-call-block strong {
    font-size: 0.75rem;
    color: #5856d6;
  }

  .tool-call-block pre {
    margin: 0.35rem 0 0 0;
    font-size: 0.78rem;
    font-family: monospace;
    color: var(--muted);
  }

  /* Error Banner */
  .error-banner {
    display: flex;
    gap: 0.75rem;
    padding: 0.85rem 1rem;
    border: 1px solid rgba(255, 59, 48, 0.3);
    background: rgba(255, 59, 48, 0.08);
    border-radius: 6px;
    color: #ff453a;
  }

  .error-banner div {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
  }

  .error-banner strong {
    font-size: 0.85rem;
    font-weight: 600;
  }

  .error-banner p {
    margin: 0;
    font-size: 0.78rem;
    color: rgba(255, 255, 255, 0.85);
  }

  /* Code View snippet style */
  .code-sub-tabs {
    display: flex;
    align-items: center;
    justify-content: space-between;
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.65rem;
  }

  .sub-tab-buttons {
    display: flex;
  }

  .sub-tab-buttons button {
    padding: 0.25rem 0.65rem;
    border: 1px solid var(--border);
    background: rgba(255, 255, 255, 0.02);
    border-radius: 4px;
    font-size: 0.75rem;
    color: var(--muted);
    cursor: pointer;
    transition: background 0.15s ease, color 0.15s ease;
  }

  .sub-tab-buttons button.active {
    background: rgba(255, 255, 255, 0.08);
    color: var(--text);
    border-color: rgba(255, 255, 255, 0.25);
  }

  .copy-btn {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    background: none;
    border: none;
    cursor: pointer;
    color: var(--muted);
    font-size: 0.75rem;
    font-weight: 500;
    transition: color 0.15s ease;
  }

  .copy-btn:hover {
    color: var(--text);
  }

  .code-output-block {
    display: flex;
    flex-direction: column;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: rgba(0, 0, 0, 0.2);
    overflow: hidden;
  }

  .code-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.65rem 0.85rem;
    background: rgba(255, 255, 255, 0.02);
    border-bottom: 1px solid var(--border);
  }

  .code-header span {
    font-size: 0.68rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: var(--muted);
  }

  .code-header strong {
    font-size: 0.78rem;
    font-family: monospace;
    color: var(--text);
  }

  .code-pre {
    margin: 0;
    padding: 1rem;
    overflow: auto;
    font-size: 0.82rem;
    font-family: var(--font-mono, monospace);
    line-height: 1.45;
  }

  /* Raw logs view styling */
  .raw-section {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .raw-title {
    font-size: 0.75rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--muted);
  }

  .raw-headers-pre,
  .raw-body-pre {
    margin: 0;
    padding: 0.85rem;
    border: 1px solid var(--border);
    border-radius: 5px;
    background: rgba(0, 0, 0, 0.2);
    font-family: monospace;
    font-size: 0.8rem;
    overflow: auto;
    line-height: 1.4;
  }

  .raw-body-pre {
    max-height: 380px;
  }

  /* Loading placeholders & animations */
  .loading-placeholder {
    color: var(--muted);
    font-style: italic;
    font-size: 0.82rem;
  }

  .spinning-icon {
    display: inline-block;
    animation: spin 1s linear infinite;
  }

  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
  }

  /* Shimmering message loading effect */
  .chat-message.assistant-msg.shimmer {
    background: linear-gradient(
      90deg,
      rgba(255, 255, 255, 0.01) 25%,
      rgba(255, 255, 255, 0.02) 50%,
      rgba(255, 255, 255, 0.01) 75%
    );
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
  }

  @keyframes shimmer {
    0% { background-position: -200% 0; }
    100% { background-position: 200% 0; }
  }

  @media (max-width: 900px) {
    .playground-page-overlay {
      grid-template-columns: 1fr;
    }
    .composer-sidebar {
      border-right: none;
      border-bottom: 1px solid var(--border);
    }
  }
</style>
