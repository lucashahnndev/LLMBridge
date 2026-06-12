<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount, tick } from 'svelte';
  import {
    fetchAppTokens,
    fetchHealth,
    fetchModelQueues,
    fetchProviderKeys,
    fetchRuntimeConfig,
    fetchUsageLogs,
    peekAppToken,
    getStoredAdminToken,
    type AppToken,
    type ModelQueue,
    type ProviderKey,
    type UsageLog
  } from '$lib/api';
  import { Copy, Check, ChevronLeft, RefreshCw, Sparkles, ShieldAlert, Code2, Settings as SettingsIcon, Terminal } from 'lucide-svelte';
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
  let selectedAppTokenId = '';
  let selectedAppToken: AppToken | null = null;
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
  let activeOutputTab: 'code' | 'raw' = 'code';
  let inspectorOpen = false;
  let chatHistoryContainer: HTMLDivElement;

  async function scrollToBottom() {
    await tick();
    if (chatHistoryContainer) {
      chatHistoryContainer.scrollTop = chatHistoryContainer.scrollHeight;
    }
  }

  function handleInputKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      if (!requestRunning && resolvedModel && appTokenValue.trim()) {
        void runRequest();
      }
    }
  }

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

  async function loadSelectedAppToken(tokenId = selectedAppTokenId) {
    const normalizedTokenId = tokenId.trim();
    if (!normalizedTokenId) {
      selectedAppTokenId = '';
      selectedAppToken = null;
      appTokenValue = '';
      return;
    }

    const chosenToken = appTokens.find((token) => String(token.id) === normalizedTokenId);
    if (!chosenToken) {
      selectedAppTokenId = '';
      selectedAppToken = null;
      appTokenValue = '';
      requestError = 'Select a valid app token.';
      return;
    }

    selectedAppTokenId = String(chosenToken.id);
    selectedAppToken = chosenToken;
    requestError = '';

    try {
      const tokenDetails = await peekAppToken(adminToken, chosenToken.id);
      if (selectedAppTokenId === String(chosenToken.id)) {
        appTokenValue = tokenDetails.token;
      }
    } catch (error) {
      if (selectedAppTokenId === String(chosenToken.id)) {
        appTokenValue = '';
        requestError = error instanceof Error ? error.message : 'Failed to load the selected app token';
      }
    }
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

      const preferredToken = apps.find((token) => token.is_active) ?? apps[0] ?? null;
      if (preferredToken) {
        await loadSelectedAppToken(String(preferredToken.id));
      } else {
        selectedAppTokenId = '';
        selectedAppToken = null;
        appTokenValue = '';
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
      requestError = 'Select a valid app token first.';
      return;
    }

    if (!resolvedModel.trim()) {
      requestError = 'Select a target model or queue.';
      return;
    }

    requestRunning = true;
    requestError = '';
    responseSummary = null;
    void scrollToBottom();

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
      void scrollToBottom();
    }
  }

  function loadExample() {
    protocol = 'anthropic';
    targetMode = 'queue';
    queueName = 'gemini';
    systemPrompt = DEFAULT_SYSTEM_PROMPT;
    userPrompt = 'Use the configured queue and explain which target would be tried first.';
    temperature = 0.2;
    maxTokens = 256;
    topP = 1;
    toolCallingEnabled = true;
    codeTab = 'curl';
    activeOutputTab = 'code';
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

  <!-- Left Side: Config Panel (320px) -->
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
        <select bind:value={selectedAppTokenId} on:change={() => void loadSelectedAppToken()}>
          <option value="" disabled>Select an app token</option>
          {#each appTokens as token}
            <option value={String(token.id)}>
              {token.name} · {token.masked_token} · {token.environment}
            </option>
          {/each}
        </select>
      </label>
      <p class="field-help">
        {#if selectedAppToken}
          {selectedAppToken.is_active ? 'Selected token is active.' : 'Selected token is inactive.'}
        {:else}
          Choose one of the app tokens already registered in the system.
        {/if}
      </p>
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
  </aside>

  <!-- Middle Column: Interactive Chat Workspace -->
  <section class="chat-workspace">
    <div class="chat-header">
      <div class="chat-header-title">
        <h3>Playground Console</h3>
        {#if responseSummary}
          <div class="chat-header-meta">
            <span class="status-badge {responseSummary.status >= 200 && responseSummary.status < 300 ? 'status-ok' : 'status-err'}">
              HTTP {responseSummary.status}
            </span>
            <span class="latency-badge">{formatLatency(responseSummary.latencyMs)}</span>
          </div>
        {/if}
      </div>
      <div class="chat-header-actions">
        <button type="button" class="inspector-toggle-btn" class:active={inspectorOpen} on:click={() => inspectorOpen = !inspectorOpen} title="Toggle Code & Raw Inspector">
          <Code2 size={14} strokeWidth={1.8} />
          <span>{inspectorOpen ? 'Hide Details' : 'Show Details'}</span>
        </button>
      </div>
    </div>

    <div class="chat-history" bind:this={chatHistoryContainer}>
      <!-- System prompt card at the top -->
      {#if systemPrompt}
        <div class="system-prompt-card">
          <div class="system-card-header">
            <span class="system-icon"><SettingsIcon size={12} strokeWidth={2} /></span>
            <span>SYSTEM PROMPT</span>
          </div>
          <div class="system-card-body">
            {systemPrompt}
          </div>
        </div>
      {/if}

      {#if !responseSummary && !requestRunning && !requestError}
        <div class="chat-empty-state">
          <div class="empty-icon"><Sparkles size={28} strokeWidth={1.2} /></div>
          <h3>Interactive LLM Gateway Playground</h3>
          <p>Configure routing parameters on the left, type a prompt message below, and click Run to test gateway key rotation, metrics, and latency.</p>
        </div>
      {:else}
        <!-- User Bubble -->
        <div class="chat-bubble user-bubble">
          <div class="bubble-sender">USER</div>
          <div class="bubble-body">{userPrompt}</div>
        </div>

        <!-- Assistant Bubble -->
        {#if requestRunning}
          <div class="chat-bubble assistant-bubble loading-bubble">
            <div class="bubble-sender">LLMBRIDGE</div>
            <div class="bubble-body">
              <span class="shimmer-text">Processing request... routing keys...</span>
            </div>
          </div>
        {:else if requestError}
          <div class="chat-bubble error-bubble">
            <div class="bubble-sender">GATEWAY ERROR</div>
            <div class="bubble-body">
              <div class="error-banner">
                <ShieldAlert size={16} strokeWidth={1.8} />
                <div>
                  <strong>Request Failed</strong>
                  <p>{requestError}</p>
                </div>
              </div>
            </div>
          </div>
        {:else if responseSummary}
          <div class="chat-bubble assistant-bubble">
            <div class="bubble-sender">ASSISTANT</div>
            <div class="bubble-body">
              <pre class="chat-pre">{responseSummary.assistantText || 'No reply text returned.'}</pre>
            </div>
          </div>

          {#if responseSummary.toolCalls.length}
            <div class="chat-bubble tool-bubble">
              <div class="bubble-sender">RESOLVED TOOL CALLS</div>
              <div class="bubble-body">
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
      {/if}
    </div>

    <!-- Chat input area at bottom -->
    <div class="chat-input-container">
      <div class="chat-input-row">
        <textarea
          bind:value={userPrompt}
          placeholder="Type user message here... (Press Enter to run, Shift+Enter for new line)"
          rows="1"
          on:keydown={handleInputKeydown}
          spellcheck="false"
        ></textarea>
        
        <button
          type="button"
          class="send-btn"
          on:click={runRequest}
          disabled={requestRunning || !resolvedModel || !appTokenValue.trim()}
        >
          {#if requestRunning}
            <span class="spinning-icon"><RefreshCw size={13} strokeWidth={2} /></span>
            <span>Running</span>
          {:else}
            <Sparkles size={13} strokeWidth={2} />
            <span>Run</span>
          {/if}
        </button>
      </div>
      <div class="chat-input-footer">
        <span class="target-indicator">
          Resolved Target: <strong>{resolvedModel || '—'}</strong>
        </span>
      </div>
    </div>
  </section>

  <!-- Right Side: Code & Raw Inspector (Collapsible) -->
  <aside class="inspector-sidebar" class:open={inspectorOpen}>
    <div class="inspector-header">
      <div class="tabs-buttons">
        <button class:active={activeOutputTab === 'code'} on:click={() => activeOutputTab = 'code'}>
          Code Snippets
        </button>
        <button class:active={activeOutputTab === 'raw'} on:click={() => activeOutputTab = 'raw'}>
          Raw Details
        </button>
      </div>
    </div>
    
    <div class="inspector-content">
      {#if activeOutputTab === 'code'}
        <div class="code-view">
          <div class="code-sub-tabs">
            <div class="sub-tab-buttons">
              <button class:active={codeTab === 'curl'} on:click={() => codeTab = 'curl'}>cURL</button>
              <button class:active={codeTab === 'js'} on:click={() => codeTab = 'js'}>JavaScript</button>
              <button class:active={codeTab === 'json'} on:click={() => codeTab = 'json'}>JSON</button>
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
        <div class="raw-view">
          {#if !responseSummary}
            <div class="empty-state">
              <h3>No Response Details</h3>
              <p>Run a request first to inspect response headers and raw response body.</p>
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
  </aside>
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
    display: flex;
    background: var(--bg);
    color: var(--text);
    overflow: hidden;
  }

  /* Left Side: Sidebar/Composer */
  .composer-sidebar {
    width: 320px;
    flex-shrink: 0;
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

  /* Center Workspace: Chat Mode */
  .chat-workspace {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
    background: rgba(10, 12, 16, 0.3);
    height: 100%;
  }

  .chat-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 48px;
    padding: 0 1.25rem;
    border-bottom: 1px solid var(--border);
    background: rgba(13, 17, 22, 0.45);
    flex-shrink: 0;
  }

  .chat-header-title {
    display: flex;
    align-items: center;
    gap: 0.85rem;
  }

  .chat-header-title h3 {
    margin: 0;
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--text);
  }

  .chat-header-meta {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .chat-header-actions {
    display: flex;
    align-items: center;
  }

  .inspector-toggle-btn {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.25rem 0.65rem;
    border: 1px solid var(--border);
    background: rgba(255, 255, 255, 0.02);
    border-radius: 4px;
    color: var(--muted);
    font-size: 0.72rem;
    cursor: pointer;
    transition: all 0.15s ease;
  }

  .inspector-toggle-btn:hover,
  .inspector-toggle-btn.active {
    color: var(--text);
    border-color: rgba(255, 255, 255, 0.2);
    background: rgba(255, 255, 255, 0.08);
  }

  .chat-history {
    flex: 1;
    overflow-y: auto;
    padding: 1.5rem;
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
    min-height: 0;
  }

  .chat-empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    flex: 1;
    gap: 0.5rem;
    color: var(--muted);
  }

  .chat-empty-state .empty-icon {
    color: rgba(216, 184, 88, 0.8);
    margin-bottom: 0.5rem;
  }

  .chat-empty-state h3 {
    margin: 0;
    font-size: 0.95rem;
    font-weight: 600;
    color: var(--text);
  }

  .chat-empty-state p {
    margin: 0;
    font-size: 0.8rem;
    max-width: 44ch;
    line-height: 1.45;
  }

  /* Chat Bubbles */
  .chat-bubble {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    padding: 0.85rem 1rem;
    border-radius: 6px;
    border: 1px solid var(--border);
    max-width: 85%;
    line-height: 1.5;
  }

  .user-bubble {
    align-self: flex-end;
    background: rgba(255, 255, 255, 0.015);
    border-left: 2px solid var(--muted);
  }

  .assistant-bubble {
    align-self: flex-start;
    background: rgba(216, 184, 88, 0.01);
    border-left: 2px solid rgba(216, 184, 88, 0.65);
  }

  .tool-bubble {
    align-self: flex-start;
    background: rgba(88, 86, 214, 0.01);
    border-left: 2px solid #5856d6;
    max-width: 90%;
  }

  .error-bubble {
    align-self: flex-start;
    border-left: 2px solid #ff3b30;
    background: rgba(255, 59, 48, 0.02);
    width: 100%;
    max-width: 600px;
  }

  .bubble-sender {
    font-size: 0.62rem;
    font-weight: 700;
    color: var(--muted);
    letter-spacing: 0.06em;
  }

  .bubble-body {
    font-size: 0.85rem;
    color: var(--text);
  }

  .chat-pre {
    margin: 0;
    white-space: pre-wrap;
    font-family: var(--font-mono, monospace);
    font-size: 0.82rem;
    line-height: 1.45;
  }

  /* System Prompt Card */
  .system-prompt-card {
    align-self: flex-start;
    border: 1px solid var(--border);
    border-radius: 6px;
    background: rgba(255, 255, 255, 0.01);
    padding: 0.75rem 1rem;
    max-width: 100%;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }

  .system-card-header {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: 0.62rem;
    font-weight: 700;
    color: var(--muted);
    letter-spacing: 0.06em;
  }

  .system-card-header .system-icon {
    display: flex;
    align-items: center;
    color: rgba(216, 184, 88, 0.7);
  }

  .system-card-body {
    font-size: 0.78rem;
    font-family: var(--font-mono, monospace);
    line-height: 1.45;
    color: var(--muted);
  }

  /* Chat Input Area */
  .chat-input-container {
    border-top: 1px solid var(--border);
    padding: 1rem 1.25rem;
    background: rgba(13, 17, 22, 0.45);
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    flex-shrink: 0;
  }

  .chat-input-row {
    display: flex;
    gap: 0.75rem;
    align-items: flex-end;
  }

  .chat-input-row textarea {
    flex: 1;
    min-height: 40px;
    max-height: 160px;
    resize: none;
    background: rgba(0, 0, 0, 0.2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 0.6rem 0.85rem;
    font-size: 0.85rem;
    color: var(--text);
    font-family: inherit;
    line-height: 1.45;
  }

  .send-btn {
    height: 38px;
    display: flex;
    align-items: center;
    gap: 0.45rem;
    padding: 0 1.15rem;
    background: #ead48f;
    color: #111;
    border: none;
    border-radius: 6px;
    font-weight: 600;
    font-size: 0.8rem;
    cursor: pointer;
    flex-shrink: 0;
    transition: opacity 0.15s ease;
  }

  .send-btn:hover:not(:disabled) {
    opacity: 0.9;
  }

  .send-btn:disabled {
    background: rgba(255, 255, 255, 0.04);
    color: var(--muted);
    border: 1px solid var(--border);
    cursor: not-allowed;
  }

  .chat-input-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-size: 0.68rem;
    color: var(--muted);
  }

  .target-indicator strong {
    color: rgba(216, 184, 88, 0.85);
  }

  /* Right Side Collapsible Inspector */
  .inspector-sidebar {
    width: 0;
    opacity: 0;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    background: rgba(13, 17, 22, 0.25);
    transition: width 200ms cubic-bezier(0.4, 0, 0.2, 1), opacity 200ms ease;
    overflow: hidden;
  }

  .inspector-sidebar.open {
    width: 380px;
    opacity: 1;
    border-left: 1px solid var(--border);
  }

  .inspector-header {
    height: 48px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    padding: 0 1rem;
    flex-shrink: 0;
    background: rgba(13, 17, 22, 0.45);
  }

  .inspector-content {
    flex: 1;
    overflow-y: auto;
    padding: 1.25rem;
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
    min-height: 0;
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

  .code-view, .raw-view {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
    min-height: 100%;
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
    gap: 0.25rem;
  }

  .sub-tab-buttons button {
    padding: 0.25rem 0.65rem;
    border: 1px solid var(--border);
    background: rgba(255, 255, 255, 0.02);
    border-radius: 4px;
    font-size: 0.72rem;
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
    font-family: var(--font-mono, monospace);
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
    font-family: var(--font-mono, monospace);
    font-size: 0.8rem;
    overflow: auto;
    line-height: 1.4;
  }

  .raw-body-pre {
    max-height: 380px;
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    text-align: center;
    flex: 1;
    gap: 0.5rem;
    color: var(--muted);
    padding: 2rem 0;
  }

  .empty-state h3 {
    margin: 0;
    font-size: 0.85rem;
    font-weight: 600;
    color: var(--text);
  }

  .empty-state p {
    margin: 0;
    font-size: 0.78rem;
    line-height: 1.4;
  }



  .shimmer-text {
    font-style: italic;
    animation: pulse 1.5s infinite;
  }

  @keyframes pulse {
    0% { opacity: 0.45; }
    50% { opacity: 0.85; }
    100% { opacity: 0.45; }
  }

  .spinning-icon {
    display: inline-block;
    animation: spin 1s linear infinite;
  }

  @keyframes spin {
    from { transform: rotate(0deg); }
    to { transform: rotate(360deg); }
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
    font-family: var(--font-mono, monospace);
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

  @media (max-width: 900px) {
    .playground-page-overlay {
      flex-direction: column;
    }
    .composer-sidebar {
      width: 100%;
      border-right: none;
      border-bottom: 1px solid var(--border);
    }
    .inspector-sidebar.open {
      width: 100%;
      border-left: none;
      border-top: 1px solid var(--border);
    }
  }
</style>
