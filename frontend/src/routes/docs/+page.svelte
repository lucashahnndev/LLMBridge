<script lang="ts">
  import { onMount } from 'svelte';
  import { Copy, CheckCircle2, Info, AlertCircle, Moon, Sun } from 'lucide-svelte';
  import { apiBaseUrl } from '$lib/api';

  let copiedId = '';
  let isDarkMode = false;

  async function copySnippet(id: string, code: string) {
    try {
      await navigator.clipboard.writeText(code);
      copiedId = id;
      window.setTimeout(() => {
        if (copiedId === id) {
          copiedId = '';
        }
      }, 2000);
    } catch {
      // ignore
    }
  }

  let proxyBase = 'http://127.0.0.1:8009';

  $: curlExample = `curl -X POST ${proxyBase}/v1/messages \\
  -H "Authorization: Bearer my-app-token" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "queue/production",
    "messages": [
      { "role": "user", "content": "Hello, how are you?" }
    ]
  }'`;

  $: claudeCodeSettings = `{
  "claudeCode.preferredLocation": "panel",
  "claudeCode.environmentVariables": [
    {
      "name": "ANTHROPIC_BASE_URL",
      "value": "${proxyBase}"
    },
    {
      "name": "ANTHROPIC_AUTH_TOKEN",
      "value": "my-app-token"
    },
    {
      "name": "ANTHROPIC_MODEL",
      "value": "queue/production"
    }
  ]
}`;

  $: claudeTerminalSession = `export ANTHROPIC_BASE_URL="${proxyBase}"
export ANTHROPIC_AUTH_TOKEN="app-token-example"
export ANTHROPIC_MODEL="queue/gemini"
claude`;

  $: claudeBashrcSetup = `cat <<'EOF' >> ~/.bashrc
export ANTHROPIC_BASE_URL="${proxyBase}"
export ANTHROPIC_AUTH_TOKEN="app-token-example"
export ANTHROPIC_MODEL="queue/gemini"
EOF
source ~/.bashrc`;

  $: claudeWindowsCmdSetup = `setx ANTHROPIC_BASE_URL "${proxyBase}"
setx ANTHROPIC_AUTH_TOKEN "app-token-example"
setx ANTHROPIC_MODEL "queue/gemini"`;

  $: jsExample = `const response = await fetch('${proxyBase}/v1/messages', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer my-app-token',
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    model: 'github/openai/gpt-4.1',
    messages: [{ role: 'user', content: 'Explain quantum computing.' }]
  })
});

const data = await response.json();
console.log(data.content[0].text);`;

  const responseExample = `{
  "id": "msg_01XFD",
  "type": "message",
  "role": "assistant",
  "model": "gemini-3.1-flash",
  "content": [
    {
      "type": "text",
      "text": "Hello! I am functioning normally."
    }
  ]
}`;

  const canonicalRequestIR = `{
  "request_id": "req_01J0",
  "protocol_in": "anthropic",
  "route": { "kind": "queue", "value": "queue/gemini" },
  "messages": [
    { "role": "system", "content": "You are a concise assistant." },
    { "role": "user", "content": "Use the calculator tool." }
  ],
  "tools": [
    {
      "name": "calculator",
      "input_schema": {
        "type": "object",
        "properties": { "expression": { "type": "string" } },
        "required": ["expression"]
      }
    }
  ],
  "metadata": { "client": "claude-code" },
  "optimization": {
    "enabled": false,
    "mode": "off",
    "compress_metadata": true,
    "drop_transport_noise": true,
    "preserve_tool_semantics": true
  },
  "telemetry": { "app_token_id": "app_123" }
}`;

  const canonicalResponseIR = `{
  "request_id": "req_01J0",
  "protocol_out": "anthropic",
  "model": "github/openai/gpt-4.1",
  "finish_reason": "tool_use",
  "content": [
    { "type": "text", "text": "I will use the calculator tool." },
    { "type": "tool_use", "id": "call_1", "name": "calculator", "input": { "expression": "2 + 2" } }
  ],
  "usage": { "input_tokens": 120, "output_tokens": 34, "total_tokens": 154 }
}`;

  $: openaiCurl = `curl -X POST ${proxyBase}/v1/chat/completions \\
  -H "Authorization: Bearer my-app-token" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "queue/production",
    "messages": [
      { "role": "user", "content": "Say hello." }
    ]
  }'`;

  onMount(() => {
    document.documentElement.classList.add('docs-html');
    document.body.classList.add('docs-page');

    proxyBase = apiBaseUrl().replace(/\/api\/v1$/, '');

    // Check local storage or system preference
    const storedTheme = localStorage.getItem('docs-theme');
    if (storedTheme === 'dark') {
      isDarkMode = true;
    } else if (storedTheme === 'light') {
      isDarkMode = false;
    } else {
      isDarkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;
    }

    return () => {
      document.documentElement.classList.remove('docs-html');
      document.body.classList.remove('docs-page');
    };
  });

  function toggleTheme() {
    isDarkMode = !isDarkMode;
    localStorage.setItem('docs-theme', isDarkMode ? 'dark' : 'light');
  }

  $: if (typeof document !== 'undefined') {
    if (isDarkMode) {
      document.body.classList.add('docs-dark');
    } else {
      document.body.classList.remove('docs-dark');
    }
  }
</script>

<svelte:head>
  <title>API Reference - LLMBridge</title>
</svelte:head>

<div class="redoc-layout">
  <!-- Left Sidebar -->
  <aside class="redoc-sidebar">
    <div class="sidebar-header">
      <div class="header-top">
        <strong>LLMBridge</strong>
        <button class="theme-toggle" on:click={toggleTheme} aria-label="Toggle Theme">
          {#if isDarkMode}
            <Sun size={18} />
          {:else}
            <Moon size={18} />
          {/if}
        </button>
      </div>
      <span>API Reference v1.0</span>
    </div>
    <div class="sidebar-search">
      <input type="text" placeholder="Search..." disabled />
    </div>
    <nav class="sidebar-nav">
      <div class="nav-section">
        <strong>Getting Started</strong>
        <a href="#quickstart">Quickstart</a>
        <a href="#runtime-setup">Runtime Setup</a>
      </div>
      <div class="nav-section">
        <strong>Core Concepts</strong>
        <a href="#app-tokens">App Tokens</a>
        <a href="#provider-keys">Provider Keys</a>
        <a href="#queues">Queues & Routing</a>
        <a href="#canonical-ir">Canonical IR</a>
        <a href="#telegram-bot">Telegram Bot</a>
      </div>
      <div class="nav-section">
        <strong>API Endpoints</strong>
        <a href="#authentication">Authentication</a>
        <a href="#anthropic-api">Anthropic API</a>
        <a href="#openai-api">OpenAI API</a>
      </div>
      <div class="nav-section">
        <strong>Operations</strong>
        <a href="#errors">Errors & Troubleshooting</a>
      </div>
    </nav>
  </aside>

  <!-- Main Content Area -->
  <main class="redoc-main">
    
    <!-- Section: Quickstart -->
    <div class="api-section" id="quickstart">
      <div class="api-text">
        <h1>LLMBridge API</h1>
        <p>
          LLMBridge is an AI API Gateway designed to stabilize upstream provider APIs.
          It accepts the client protocol at the edge, normalizes it into an internal routing model, and adapts only at the provider boundary so tool calls and routing intent stay intact.
        </p>

        <h2>Quickstart</h2>
        <p>To start routing requests through the gateway, follow this strict sequence of operations in the Admin Dashboard:</p>
        <ol>
          <li><strong>Configure runtime:</strong> Set the backend host and port in the runtime config.</li>
          <li><strong>Create an App Token:</strong> Generate a token for your client applications.</li>
          <li><strong>Add Provider Keys:</strong> Register upstream API keys (e.g., OpenAI, Google).</li>
          <li><strong>Create Queues:</strong> Group your models into logical queues to enable fallback.</li>
          <li><strong>Send Requests:</strong> Point your client code to the gateway URL using your App Token and target your queue alias.</li>
        </ol>
      </div>
      <div class="api-code">
        <!-- Empty or introductory code block -->
        <div class="code-panel">
          <div class="code-header">BASE URL</div>
          <pre><code>{proxyBase}</code></pre>
        </div>
      </div>
    </div>

    <!-- Section: Runtime Setup -->
    <div class="api-section" id="runtime-setup">
      <div class="api-text">
        <h2>Runtime Setup</h2>
        <p>
          The gateway consists of a frontend administrative dashboard and a backend API engine. The backend must be bound to a local or public host.
        </p>
        <div class="callout callout-info">
          <Info size={16} />
          <div>
            <strong>Protocol contract</strong>
            <p>Public Anthropic and OpenAI-like requests are preserved at the edge. Internally, the gateway uses a richer routing model and only converts at the provider boundary.</p>
          </div>
        </div>
        <div class="callout callout-info">
          <Info size={16} />
          <div>
            <strong>Restart Required</strong>
            <p>If you modify the Host or Port settings in the Runtime section of the dashboard, you must restart the backend process for the changes to take effect at the socket level.</p>
          </div>
        </div>
      </div>
      <div class="api-code"></div>
    </div>

    <!-- Section: Canonical IR -->
    <div class="api-section" id="canonical-ir">
      <div class="api-text">
        <h2>Canonical IR</h2>
        <p>
          The internal model keeps routing, message order, tool calls, response intent, and cleanup policy intact.
          Optional cleanup can remove provider noise and redundant metadata, but only as a feature flag.
        </p>

        <h3>Preserve / Compress / Drop</h3>
        <table class="redoc-table">
          <thead>
            <tr>
              <th>Category</th>
              <th>Rule</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><strong>Preserve</strong></td>
              <td>Messages, roles, tool calls, tool results, system prompts, route targets, streaming intent, response IDs, ordering, and finish reasons.</td>
            </tr>
            <tr>
              <td><strong>Compress</strong></td>
              <td>Client metadata, provider noise, duplicate headers, and other non-essential envelope fields. Only when the cleanup flag is enabled.</td>
            </tr>
            <tr>
              <td><strong>Drop from agent payload</strong></td>
              <td>Secrets, transport headers, debug-only fields, and internal telemetry tags.</td>
            </tr>
            <tr>
              <td><strong>Policy</strong></td>
              <td>Cleanup is opt-in and can be set to off, conservative, or aggressive per route or request.</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="api-code">
        <div class="code-panel">
          <div class="code-header">Canonical Request IR</div>
          <pre><code>{canonicalRequestIR}</code></pre>
        </div>
        <div class="code-panel">
          <div class="code-header">Canonical Response IR</div>
          <pre><code>{canonicalResponseIR}</code></pre>
        </div>
      </div>
    </div>

    <!-- Section: App Tokens & Auth -->
    <div class="api-section" id="authentication">
      <div class="api-text">
        <h2>Authentication</h2>
        <p>
          App Tokens represent your downstream clients (e.g., an internal service, a mobile app, or Claude Code). 
          These tokens must be included in the <code>Authorization: Bearer &lt;token&gt;</code> header of every request made to the gateway.
        </p>
        <div class="callout callout-warning">
          <AlertCircle size={16} />
          <div>
            <strong>Missing or invalid token</strong>
            <p>Failing to provide a valid, active App Token will immediately result in a <code>401 Unauthorized</code> response.</p>
          </div>
        </div>
      </div>
      <div class="api-code">
        <div class="code-panel">
          <div class="code-header">AUTHORIZATION HEADER</div>
          <button class="copy-btn" on:click={() => copySnippet('auth', 'Authorization: Bearer my-app-token')}>
            {#if copiedId === 'auth'}<CheckCircle2 size={14}/>{:else}<Copy size={14}/>{/if}
          </button>
          <pre><code>Authorization: Bearer my-app-token</code></pre>
        </div>
      </div>
    </div>

    <!-- Section: Provider Keys -->
    <div class="api-section" id="provider-keys">
      <div class="api-text">
        <h2>Provider Keys</h2>
        <p>
          Provider keys are your actual billing credentials for upstream AI providers (OpenAI, Anthropic, Google, OpenRouter).
          The gateway securely holds these keys and injects them into downstream requests through provider adapters.
        </p>
        <table class="redoc-table">
          <thead>
            <tr>
              <th>State</th>
              <th>Behavior</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><span class="badge active">ACTIVE</span></td>
              <td>Key is healthy and available for routing.</td>
            </tr>
            <tr>
              <td><span class="badge cooldown">COOLDOWN</span></td>
              <td>Key is suspended due to 429 Too Many Requests or 500 errors.</td>
            </tr>
            <tr>
              <td><span class="badge invalid">INVALID</span></td>
              <td>Key returned a 401/403. It will not be used until manually verified.</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="api-code"></div>
    </div>

    <!-- Section: Queues -->
    <div class="api-section" id="queues">
      <div class="api-text">
        <h2>Queues & Routing</h2>
        <p>
          Queues map an abstract model target (e.g., <code>queue/production</code>) to an ordered list of real models.
          The routing layer can keep the order fixed, re-rank candidates, or prefer latency-aware selection.
        </p>

        <h3>Routing Patterns</h3>
        <table class="redoc-table">
          <thead>
            <tr>
              <th>Pattern</th>
              <th>Use Case</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td><code>provider/downstream-target</code></td>
              <td>Target a specific provider unconditionally (e.g., <code>github/openai/gpt-4.1</code> or <code>google/gemini-1.5-pro</code>). Fails directly if the provider errors.</td>
            </tr>
            <tr>
              <td><code>queue/queue_name</code></td>
              <td>Target a managed queue. Evaluates candidates based on the queue strategy and fails over automatically.</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="api-code">
        <div class="code-panel">
          <div class="code-header">Claude Code Integration (JSON)</div>
          <button class="copy-btn" on:click={() => copySnippet('claude', claudeCodeSettings)}>
            {#if copiedId === 'claude'}<CheckCircle2 size={14}/>{:else}<Copy size={14}/>{/if}
          </button>
          <pre><code>{claudeCodeSettings}</code></pre>
        </div>

        <h3>Terminal Setup</h3>
        <p>
          Set the env vars in the current shell for a quick test, or persist them in your shell profile so Claude Code always opens on this gateway.
        </p>
        <div class="code-panel">
          <div class="code-header">Linux / macOS session</div>
          <pre><code>{claudeTerminalSession}</code></pre>
        </div>
        <div class="code-panel">
          <div class="code-header">Linux / macOS default</div>
          <pre><code>{claudeBashrcSetup}</code></pre>
        </div>
        <div class="code-panel">
          <div class="code-header">Windows CMD default</div>
          <pre><code>{claudeWindowsCmdSetup}</code></pre>
        </div>
      </div>
    </div>

    <!-- Section: Telegram Bot -->
    <div class="api-section" id="telegram-bot">
      <div class="api-text">
        <h2>Telegram Bot</h2>
        <p>
          The built-in Telegram bot can report runtime state, list app tokens, providers, and queues, and toggle alert switches from the chat you bind with <code>/link</code>.
        </p>

        <h3>Commands</h3>
        <ul class="param-list">
          <li>
            <div class="param-name">/status</div>
            <div class="param-desc">Service version and runtime base URL.</div>
          </li>
          <li>
            <div class="param-name">/apps, /providers, /queues</div>
            <div class="param-desc">Short operational summaries.</div>
          </li>
          <li>
            <div class="param-name">/app &lt;id|name&gt;, /provider &lt;name&gt;, /queue &lt;name&gt;</div>
            <div class="param-desc">Focused overview for a specific object.</div>
          </li>
          <li>
            <div class="param-name">/alerts, /alerts proxy on|off, /alerts queue on|off</div>
            <div class="param-desc">Inspect or toggle Telegram alerts.</div>
          </li>
          <li>
            <div class="param-name">/link</div>
            <div class="param-desc">Bind the current chat to the bot when no chat ID is configured yet.</div>
          </li>
        </ul>
      </div>
      <div class="api-code">
        <div class="code-panel">
          <div class="code-header">Example Session</div>
          <pre><code>/link
/apps
/provider github
/queue gemini
/alerts proxy off</code></pre>
        </div>
      </div>
    </div>

    <!-- Section: Anthropic API -->
    <div class="api-section" id="anthropic-api">
      <div class="api-text">
        <div class="endpoint-badge">
          <span class="method post">POST</span>
          <span class="path">/v1/messages</span>
        </div>
        <h2>Create a Message (Anthropic Protocol)</h2>
        <p>The gateway implements the Anthropic <code>/v1/messages</code> standard. It acts as an adapter, parsing Anthropic payloads and preserving them through the internal routing model before rebuilding the Anthropic response on the way out.</p>
        
        <h3>Body Parameters</h3>
        <ul class="param-list">
          <li>
            <div class="param-name">model <span class="param-type">string</span> <span class="param-req">required</span></div>
            <div class="param-desc">The routing target. Use <code>queue/&lt;name&gt;</code> or <code>&lt;provider&gt;/&lt;model&gt;</code>.</div>
          </li>
          <li>
            <div class="param-name">messages <span class="param-type">array</span> <span class="param-req">required</span></div>
            <div class="param-desc">Input messages. Each object must have a <code>role</code> and <code>content</code>.</div>
          </li>
          <li>
            <div class="param-name">max_tokens <span class="param-type">integer</span></div>
            <div class="param-desc">The maximum number of tokens to generate.</div>
          </li>
        </ul>
      </div>
      <div class="api-code">
        <div class="code-panel">
          <div class="code-header">Example Request (cURL)</div>
          <button class="copy-btn" on:click={() => copySnippet('curl', curlExample)}>
            {#if copiedId === 'curl'}<CheckCircle2 size={14}/>{:else}<Copy size={14}/>{/if}
          </button>
          <pre><code>{curlExample}</code></pre>
        </div>

        <div class="code-panel">
          <div class="code-header">Example Request (Node.js)</div>
          <button class="copy-btn" on:click={() => copySnippet('js', jsExample)}>
            {#if copiedId === 'js'}<CheckCircle2 size={14}/>{:else}<Copy size={14}/>{/if}
          </button>
          <pre><code>{jsExample}</code></pre>
        </div>

        <div class="code-panel response-panel">
          <div class="code-header">Example Response (200 OK)</div>
          <pre><code>{responseExample}</code></pre>
        </div>
      </div>
    </div>

    <!-- Section: OpenAI API -->
    <div class="api-section" id="openai-api">
      <div class="api-text">
        <div class="endpoint-badge">
          <span class="method post">POST</span>
          <span class="path">/v1/chat/completions</span>
        </div>
        <h2>Create Chat Completion (OpenAI Protocol)</h2>
        <p>Provides a native OpenAI-compatible API interface. The public contract stays OpenAI-compatible while provider-specific behavior is handled through adapters behind the scenes.</p>
        
        <h3>Body Parameters</h3>
        <ul class="param-list">
          <li>
            <div class="param-name">model <span class="param-type">string</span> <span class="param-req">required</span></div>
            <div class="param-desc">The routing target. Use <code>queue/&lt;name&gt;</code> or <code>&lt;provider&gt;/&lt;model&gt;</code>.</div>
          </li>
          <li>
            <div class="param-name">messages <span class="param-type">array</span> <span class="param-req">required</span></div>
            <div class="param-desc">An array of message objects (role, content).</div>
          </li>
        </ul>
      </div>
      <div class="api-code">
        <div class="code-panel">
          <div class="code-header">Example Request (cURL)</div>
          <button class="copy-btn" on:click={() => copySnippet('openaicurl', openaiCurl)}>
            {#if copiedId === 'openaicurl'}<CheckCircle2 size={14}/>{:else}<Copy size={14}/>{/if}
          </button>
          <pre><code>{openaiCurl}</code></pre>
        </div>
      </div>
    </div>

    <!-- Section: Errors -->
    <div class="api-section" id="errors">
      <div class="api-text">
        <h2>Errors</h2>
        <p>The gateway intercepts standard provider errors and implements failover. If all candidates fail, or if a direct route fails, the gateway surfaces the error.</p>
        
        <ul class="param-list">
          <li>
            <div class="param-name">400 Bad Request</div>
            <div class="param-desc">The payload structure was malformed or unsupported.</div>
          </li>
          <li>
            <div class="param-name">401 Unauthorized</div>
            <div class="param-desc">Missing or invalid App Token.</div>
          </li>
          <li>
            <div class="param-name">403 Forbidden</div>
            <div class="param-desc">App token is disabled or unauthorized.</div>
          </li>
          <li>
            <div class="param-name">404 Not Found</div>
            <div class="param-desc">The specified queue or direct provider does not exist.</div>
          </li>
          <li>
            <div class="param-name">429 Too Many Requests</div>
            <div class="param-desc">Your App Token hit its configured RPM limit, or all providers are exhausted.</div>
          </li>
          <li>
            <div class="param-name">502 Bad Gateway</div>
            <div class="param-desc">Queue routing failed. All candidates in the queue were exhausted or timed out.</div>
          </li>
        </ul>
      </div>
      <div class="api-code">
        <div class="code-panel response-panel">
          <div class="code-header">Example Error (401 Unauthorized)</div>
          <pre><code>{`{
  "error": {
    "type": "authentication_error",
    "message": "Invalid App Token provided."
  }
}`}</code></pre>
        </div>
      </div>
    </div>

    <div class="api-footer">
      <p>LLMBridge API Documentation</p>
    </div>
  </main>
</div>

<style>
  /* Base Variables - Light Mode */
  :root {
    --rd-bg-text: #f4f5f7;
    --rd-bg-code: #e4e7eb; /* Light grey right column */
    --rd-sidebar-bg: #f4f5f7;
    --rd-sidebar-width: 240px;
    
    --rd-text-main: #0f172a;
    --rd-text-muted: #4b5563;
    --rd-text-code: #0f172a;
    --rd-border: #d1d5db;
    --rd-border-subtle: #e5e7eb;
    --rd-accent: #b45309;
    --rd-radius-sm: 2px;
    --rd-radius-md: 3px;

    /* Code Panel (Right Side) Colors (Always Dark Mode for Code for Premium look) */
    --rd-panel-bg: #181a1f;
    --rd-panel-border: rgba(216, 184, 88, 0.15);
    --rd-panel-header-bg: rgba(255, 255, 255, 0.01);
    --rd-panel-header-text: #9ca3af;
    --rd-panel-header-border: rgba(216, 184, 88, 0.12);
    --rd-panel-code-text: #f3f4f6;
    --rd-panel-btn-color: #9ca3af;
    --rd-panel-btn-hover-bg: rgba(255, 255, 255, 0.03);
    --rd-panel-btn-hover-text: #ffffff;
    
    --rd-font-main: 'Inter', -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    --rd-font-code: 'JetBrains Mono', "Source Code Pro", Consolas, Courier, monospace;
  }

  /* Support for Dark Mode via class on body */
  :global(body.docs-dark) {
    --rd-bg-text: #0c0d0f;
    --rd-bg-code: #121417; 
    --rd-sidebar-bg: #0c0d0f;
    --rd-text-main: #f3f4f6;
    --rd-text-muted: #9ca3af;
    --rd-border: rgba(216, 184, 88, 0.12);
    --rd-border-subtle: rgba(216, 184, 88, 0.08);
    --rd-accent: #d8b858;

    /* Code Panel Colors are preserved for consistent dark developer look */
    --rd-panel-bg: #181a1f;
    --rd-panel-border: rgba(216, 184, 88, 0.15);
    --rd-panel-header-bg: rgba(255, 255, 255, 0.01);
    --rd-panel-header-text: #9ca3af;
    --rd-panel-header-border: rgba(216, 184, 88, 0.12);
    --rd-panel-code-text: #f3f4f6;
    --rd-panel-btn-color: #9ca3af;
    --rd-panel-btn-hover-bg: rgba(255, 255, 255, 0.03);
    --rd-panel-btn-hover-text: #ffffff;
  }

  /* Reset layout constraints to ensure absolute override over app.css */
  :global(html.docs-html),
  :global(body.docs-page) {
    margin: 0 !important;
    padding: 0 !important;
    background-color: var(--rd-bg-text) !important;
    background-image: none !important; /* Strip any global gradients */
  }

  /* Overall Layout */
  .redoc-layout {
    display: flex;
    min-height: 100vh;
    font-family: var(--rd-font-main);
    line-height: 1.45;
    background: var(--rd-bg-text);
    position: relative;
    z-index: 100; /* Ensure we sit above global app wrappers */
  }

  /* Sidebar */
  .redoc-sidebar {
    width: var(--rd-sidebar-width);
    flex-shrink: 0;
    background-color: var(--rd-sidebar-bg);
    border-right: 1px solid var(--rd-border);
    position: sticky;
    top: 0;
    height: 100vh;
    overflow-y: auto;
    overflow-x: hidden;
    display: flex;
    flex-direction: column;
    z-index: 10;
  }

  .sidebar-header {
    padding: 1rem 0.85rem;
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    border-bottom: 1px solid var(--rd-border);
  }

  .header-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .sidebar-header strong {
    font-size: 1.05rem;
    color: var(--rd-text-main);
    font-weight: 600;
    letter-spacing: -0.01em;
  }

  .sidebar-header span {
    font-size: 0.72rem;
    color: var(--rd-text-muted);
  }

  .theme-toggle {
    background: transparent;
    border: none;
    color: var(--rd-text-muted);
    cursor: pointer;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 0.3rem;
    border-radius: var(--rd-radius-sm);
    transition: background 0.15s, color 0.15s;
  }

  .theme-toggle:hover {
    background: rgba(128, 128, 128, 0.08);
    color: var(--rd-text-main);
  }

  .sidebar-search {
    padding: 0.75rem 0.85rem;
  }

  .sidebar-search input {
    width: 100%;
    padding: 0.45rem 0.65rem;
    border: 1px solid var(--rd-border);
    border-radius: var(--rd-radius-sm);
    background: rgba(0, 0, 0, 0.02);
    color: var(--rd-text-main);
    font-family: var(--rd-font-main);
    box-sizing: border-box;
    font-size: 0.78rem;
    transition: all 0.2s ease;
  }

  .sidebar-search input:focus {
    border-color: var(--rd-accent);
    outline: none;
  }

  .sidebar-nav {
    padding: 0 0 1.5rem 0;
    display: flex;
    flex-direction: column;
  }

  .nav-section {
    display: flex;
    flex-direction: column;
    margin-top: 1rem;
  }

  .nav-section strong {
    font-size: 0.68rem;
    text-transform: uppercase;
    color: var(--rd-text-muted);
    padding: 0.35rem 0.85rem;
    letter-spacing: 0.08em;
    font-weight: 600;
  }

  .nav-section a {
    text-decoration: none;
    color: var(--rd-text-main);
    font-size: 0.82rem;
    padding: 0.35rem 0.85rem;
    border-left: 2px solid transparent;
    transition: background 0.1s, border-color 0.1s, color 0.1s;
  }

  .nav-section a:hover {
    background-color: rgba(216, 184, 88, 0.04);
    color: var(--rd-accent);
    border-left-color: var(--rd-accent);
  }

  /* Main Content Area */
  .redoc-main {
    flex-grow: 1;
    position: relative;
    /* Redoc uses a 50/50 split */
    background: linear-gradient(to right, var(--rd-bg-text) 50%, var(--rd-bg-code) 50%) !important;
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  @media (max-width: 1000px) {
    .redoc-main {
      background: var(--rd-bg-text) !important;
    }
  }

  /* API Section (Row) */
  .api-section {
    display: flex;
    width: 100%;
    align-items: stretch;
  }

  @media (max-width: 1000px) {
    .api-section {
      flex-direction: column;
    }
  }

  /* Text Half (Left) */
  .api-text {
    width: 50%;
    box-sizing: border-box;
    padding: 2rem 2.25rem;
    background: var(--rd-bg-text);
    color: var(--rd-text-main);
    border-bottom: 1px solid var(--rd-border);
  }

  /* Code Half (Right) */
  .api-code {
    width: 50%;
    box-sizing: border-box;
    padding: 2rem 2.25rem;
    background: var(--rd-bg-code);
    display: flex;
    flex-direction: column;
    gap: 1rem;
    border-bottom: 1px solid var(--rd-border-subtle);
  }

  @media (max-width: 1000px) {
    .api-text, .api-code {
      width: 100%;
    }
    .api-text {
      padding: 1.5rem 1.25rem;
      border-bottom: none;
    }
    .api-code {
      padding: 1.5rem 1.25rem;
      border-bottom: 1px solid var(--rd-border);
    }
  }

  /* Typography */
  .api-text h1 {
    font-size: 1.6rem;
    margin: 0 0 0.75rem 0;
    font-weight: 700;
    color: var(--rd-text-main);
    letter-spacing: -0.02em;
  }

  .api-text h2 {
    font-size: 1.25rem;
    margin: 0 0 0.75rem 0;
    font-weight: 600;
    color: var(--rd-text-main);
    letter-spacing: -0.01em;
  }

  .api-text h3 {
    font-size: 0.95rem;
    margin: 1.25rem 0 0.5rem 0;
    font-weight: 600;
    color: var(--rd-text-main);
  }

  .api-text p {
    margin: 0 0 0.75rem 0;
    line-height: 1.5;
    color: var(--rd-text-main);
    font-size: 0.82rem;
    opacity: 0.9;
  }

  .api-text code {
    background: rgba(216, 184, 88, 0.05);
    border: 1px solid rgba(216, 184, 88, 0.12);
    padding: 0.1rem 0.3rem;
    border-radius: var(--rd-radius-sm);
    font-family: var(--rd-font-code);
    font-size: 0.8em;
    color: var(--rd-text-main);
  }

  /* Parameter Lists */
  .param-list {
    list-style: none;
    padding: 0;
    margin: 0.75rem 0;
  }

  .param-list li {
    padding: 0.85rem 0;
    border-bottom: 1px solid var(--rd-border);
  }

  .param-list li:last-child {
    border-bottom: none;
  }

  .param-name {
    font-family: var(--rd-font-code);
    font-weight: 600;
    font-size: 0.82rem;
    margin-bottom: 0.25rem;
    color: var(--rd-text-main);
  }

  .param-type {
    color: var(--rd-text-muted);
    font-weight: 400;
    margin-left: 0.4rem;
  }

  .param-req {
    color: #eab308;
    font-size: 0.65rem;
    font-weight: 700;
    text-transform: uppercase;
    margin-left: 0.4rem;
  }

  .param-desc {
    font-size: 0.82rem;
    color: var(--rd-text-muted);
    line-height: 1.45;
  }

  /* Endpoint Badge */
  .endpoint-badge {
    display: inline-flex;
    align-items: center;
    border: 1px solid var(--rd-border);
    border-radius: var(--rd-radius-sm);
    overflow: hidden;
    margin-bottom: 1rem;
    font-family: var(--rd-font-code);
    font-size: 0.78rem;
  }

  .method {
    padding: 0.25rem 0.5rem;
    font-weight: 600;
    color: #0c0d0f;
  }

  .method.post { background-color: #10b981; }

  .path {
    padding: 0.25rem 0.5rem;
    background: rgba(128, 128, 128, 0.05);
    color: var(--rd-text-main);
  }

  /* Callouts */
  .callout {
    display: flex;
    gap: 0.65rem;
    padding: 0.75rem 0.9rem;
    border-radius: var(--rd-radius-sm);
    background: var(--rd-sidebar-bg);
    margin: 1rem 0;
    border: 1px solid var(--rd-border);
  }

  .callout-warning { border-left: 3px solid #eab308; }
  .callout-warning :global(svg) { color: #eab308; flex-shrink: 0; margin-top: 0.1rem; }
  .callout-info { border-left: 3px solid var(--rd-accent); }
  .callout-info :global(svg) { color: var(--rd-accent); flex-shrink: 0; margin-top: 0.1rem; }

  .callout strong { display: block; margin-bottom: 0.15rem; color: var(--rd-text-main); font-weight: 600; }
  .callout p { margin: 0; font-size: 0.82rem; color: var(--rd-text-muted); }

  /* Tables */
  .redoc-table {
    width: 100%;
    border-collapse: collapse;
    margin: 1rem 0;
    font-size: 0.82rem;
    border: 1px solid var(--rd-border);
    border-radius: var(--rd-radius-sm);
    overflow: hidden;
  }

  .redoc-table th,
  .redoc-table td {
    padding: 0.65rem 0.85rem;
    text-align: left;
    border-bottom: 1px solid var(--rd-border);
    color: var(--rd-text-main);
  }

  .redoc-table th {
    color: var(--rd-text-muted);
    font-weight: 600;
    background: var(--rd-sidebar-bg);
  }

  /* Badges */
  .badge {
    padding: 0.15rem 0.45rem;
    border-radius: var(--rd-radius-sm);
    font-size: 0.68rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    border: 1px solid transparent;
  }
  .active { background: rgba(16, 185, 129, 0.08); color: #10b981; border-color: rgba(16, 185, 129, 0.15); }
  .cooldown { background: rgba(216, 184, 88, 0.08); color: #eab308; border-color: rgba(216, 184, 88, 0.15); }
  .invalid { background: rgba(239, 68, 68, 0.08); color: #ef4444; border-color: rgba(239, 68, 68, 0.15); }

  /* Code Panels (Right Side) */
  .code-panel {
    background: var(--rd-panel-bg);
    border-radius: var(--rd-radius-sm);
    border: 1px solid var(--rd-panel-border);
    position: relative;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    overflow: hidden;
  }

  .code-header {
    background: var(--rd-panel-header-bg);
    padding: 0.5rem 0.85rem;
    font-size: 0.68rem;
    color: var(--rd-panel-header-text);
    border-bottom: 1px solid var(--rd-panel-header-border);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }

  .code-panel pre {
    margin: 0;
    padding: 0.9rem 0.85rem;
    overflow-x: auto;
  }

  .code-panel code {
    font-family: var(--rd-font-code);
    font-size: 0.78rem;
    color: var(--rd-panel-code-text);
    line-height: 1.45;
    background: transparent;
  }

  .copy-btn {
    position: absolute;
    top: 0.35rem;
    right: 0.4rem;
    background: transparent;
    border: none;
    color: var(--rd-panel-btn-color);
    cursor: pointer;
    padding: 0.25rem;
    border-radius: var(--rd-radius-sm);
    transition: color 0.15s, background 0.15s;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .copy-btn:hover {
    color: var(--rd-panel-btn-hover-text);
    background: var(--rd-panel-btn-hover-bg);
  }

  .response-panel .code-header {
    color: #10b981;
  }

  .api-footer {
    padding: 1.5rem;
    text-align: center;
    color: var(--rd-text-muted);
    font-size: 0.78rem;
    background: var(--rd-bg-text);
    border-top: 1px solid var(--rd-border);
  }

  .api-footer p {
    margin: 0;
  }

  @media (max-width: 800px) {
    .redoc-sidebar {
      display: none;
    }
  }
</style>
