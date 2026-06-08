<script lang="ts">
  import { onMount } from 'svelte';
  import { Copy, CheckCircle2, Info, AlertCircle } from 'lucide-svelte';

  let copiedId = '';

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

  const curlExample = `curl -X POST http://127.0.0.1:8009/v1/messages \\
  -H "Authorization: Bearer my-app-token" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "queue/production",
    "messages": [
      { "role": "user", "content": "Hello, how are you?" }
    ]
  }'`;

  const claudeCodeSettings = `{
  "claudeCode.preferredLocation": "panel",
  "claudeCode.environmentVariables": [
    {
      "name": "ANTHROPIC_BASE_URL",
      "value": "http://127.0.0.1:8009"
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

  const jsExample = `const response = await fetch('http://127.0.0.1:8009/v1/messages', {
  method: 'POST',
  headers: {
    'Authorization': 'Bearer my-app-token',
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    model: 'google/gemini-3.1-flash',
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

  const openaiCurl = `curl -X POST http://127.0.0.1:8009/v1/chat/completions \\
  -H "Authorization: Bearer my-app-token" \\
  -H "Content-Type: application/json" \\
  -d '{
    "model": "queue/production",
    "messages": [
      { "role": "user", "content": "Say hello." }
    ]
  }'`;

  onMount(() => {
    // Redoc style scroll spy could go here
  });
</script>

<svelte:head>
  <title>API Reference - LLMKeyRotator</title>
</svelte:head>

<div class="redoc-layout">
  <!-- Left Sidebar -->
  <aside class="redoc-sidebar">
    <div class="sidebar-header">
      <strong>LLMKeyRotator</strong>
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
        <h1>LLMKeyRotator API</h1>
        <p>
          LLMKeyRotator is an AI API Gateway designed to stabilize upstream provider APIs. 
          It acts as a middle layer, receiving requests from your applications and routing them to external providers with built-in failover, load balancing, and rotation logic.
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
          <pre><code>http://127.0.0.1:8009</code></pre>
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
            <strong>Restart Required</strong>
            <p>If you modify the Host or Port settings in the Runtime section of the dashboard, you must restart the backend process for the changes to take effect at the socket level.</p>
          </div>
        </div>
      </div>
      <div class="api-code"></div>
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
          The gateway securely holds these keys and injects them into downstream requests.
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
              <td><code>provider/model_name</code></td>
              <td>Target a specific provider unconditionally (e.g., <code>google/gemini-1.5-pro</code>). Fails directly if the provider errors.</td>
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
        <p>The gateway implements the Anthropic <code>/v1/messages</code> standard. It acts as an adapter, parsing Anthropic payloads and normalizing the responses from OpenAI, Google, or OpenRouter behind the scenes.</p>
        
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
        <p>Provides a native OpenAI-compatible API interface. Downstream providers are translated back into the OpenAI schema.</p>
        
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
      <p>LLMKeyRotator API Documentation</p>
    </div>
  </main>
</div>

<style>
  /* Base Variables - Hardcoded Light/Dark Redoc Split */
  :root {
    --rd-bg-text: #ffffff;
    --rd-bg-code: #1e2227; 
    --rd-sidebar-bg: #f4f5f7;
    --rd-sidebar-width: 280px;
    
    --rd-text-main: #333333;
    --rd-text-muted: #666666;
    --rd-text-code: #c9d1d9;
    --rd-border: #e0e0e0;
    --rd-accent: #0065ff;
    
    --rd-font-main: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, "Helvetica Neue", sans-serif;
    --rd-font-code: "Source Code Pro", Consolas, Inconsolata, "Liberation Mono", Courier, monospace;
  }

  /* Support for global dark mode toggles: If the user prefers dark mode, flip the text column to dark */
  @media (prefers-color-scheme: dark) {
    :root {
      --rd-bg-text: #0d1117;
      --rd-bg-code: #161b22; 
      --rd-sidebar-bg: #090c10;
      --rd-text-main: #c9d1d9;
      --rd-text-muted: #8b949e;
      --rd-border: #30363d;
      --rd-accent: #58a6ff;
    }
  }

  /* Reset layout constraints to ensure absolute override over app.css */
  :global(body[data-route="docs"]) {
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
    line-height: 1.6;
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
    padding: 1.5rem 1.25rem;
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    border-bottom: 1px solid var(--rd-border);
  }

  .sidebar-header strong {
    font-size: 1.25rem;
    color: var(--rd-text-main);
    font-weight: 600;
  }

  .sidebar-header span {
    font-size: 0.8rem;
    color: var(--rd-text-muted);
  }

  .sidebar-search {
    padding: 1rem 1.25rem;
  }

  .sidebar-search input {
    width: 100%;
    padding: 0.6rem;
    border: 1px solid var(--rd-border);
    border-radius: 4px;
    background: transparent;
    color: var(--rd-text-main);
    font-family: var(--rd-font-main);
    box-sizing: border-box;
  }

  .sidebar-nav {
    padding: 0 0 2rem 0;
    display: flex;
    flex-direction: column;
  }

  .nav-section {
    display: flex;
    flex-direction: column;
    margin-top: 1.5rem;
  }

  .nav-section strong {
    font-size: 0.75rem;
    text-transform: uppercase;
    color: var(--rd-text-muted);
    padding: 0.5rem 1.25rem;
    letter-spacing: 0.05em;
    font-weight: 600;
  }

  .nav-section a {
    text-decoration: none;
    color: var(--rd-text-main);
    font-size: 0.9rem;
    padding: 0.4rem 1.25rem;
    border-left: 3px solid transparent;
    transition: background 0.1s, border-color 0.1s, color 0.1s;
  }

  .nav-section a:hover {
    background-color: rgba(128, 128, 128, 0.1);
    color: var(--rd-accent);
  }

  /* Main Content Area */
  .redoc-main {
    flex-grow: 1;
    position: relative;
    /* Redoc uses a 50/50 split */
    background: linear-gradient(to right, var(--rd-bg-text) 50%, var(--rd-bg-code) 50%);
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  @media (max-width: 1000px) {
    .redoc-main {
      background: var(--rd-bg-text);
    }
  }

  /* API Section (Row) */
  .api-section {
    display: flex;
    width: 100%;
  }

  @media (max-width: 1000px) {
    .api-section {
      flex-direction: column;
    }
  }

  /* Text Half (Left) */
  .api-text {
    flex: 1;
    padding: 3.5rem;
    background: var(--rd-bg-text);
    color: var(--rd-text-main);
    border-bottom: 1px solid var(--rd-border);
  }

  /* Code Half (Right) */
  .api-code {
    flex: 1;
    padding: 3.5rem;
    background: var(--rd-bg-code);
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
    border-bottom: 1px solid rgba(255, 255, 255, 0.05); /* Subtle dark border */
  }

  @media (max-width: 1000px) {
    .api-text {
      padding: 2.5rem 1.5rem;
      border-bottom: none;
    }
    .api-code {
      padding: 2rem 1.5rem;
      border-bottom: 1px solid var(--rd-border);
    }
  }

  /* Typography */
  .api-text h1 {
    font-size: 2.2rem;
    margin: 0 0 1rem 0;
    font-weight: 500;
    color: var(--rd-text-main);
  }

  .api-text h2 {
    font-size: 1.6rem;
    margin: 0 0 1rem 0;
    font-weight: 500;
    color: var(--rd-text-main);
  }

  .api-text h3 {
    font-size: 1.1rem;
    margin: 2rem 0 0.75rem 0;
    font-weight: 600;
    color: var(--rd-text-main);
  }

  .api-text p {
    margin: 0 0 1rem 0;
    line-height: 1.6;
    color: var(--rd-text-main);
  }

  .api-text code {
    background: rgba(128, 128, 128, 0.15);
    padding: 0.15em 0.35em;
    border-radius: 4px;
    font-family: var(--rd-font-code);
    font-size: 0.85em;
    color: var(--rd-text-main);
  }

  /* Parameter Lists */
  .param-list {
    list-style: none;
    padding: 0;
    margin: 1rem 0;
  }

  .param-list li {
    padding: 1.25rem 0;
    border-bottom: 1px solid var(--rd-border);
  }

  .param-list li:last-child {
    border-bottom: none;
  }

  .param-name {
    font-family: var(--rd-font-code);
    font-weight: 600;
    font-size: 0.9rem;
    margin-bottom: 0.35rem;
    color: var(--rd-text-main);
  }

  .param-type {
    color: var(--rd-text-muted);
    font-weight: 400;
    margin-left: 0.5rem;
  }

  .param-req {
    color: #d29922;
    font-size: 0.7rem;
    text-transform: uppercase;
    margin-left: 0.5rem;
  }

  .param-desc {
    font-size: 0.9rem;
    color: var(--rd-text-muted);
    line-height: 1.5;
  }

  /* Endpoint Badge */
  .endpoint-badge {
    display: inline-flex;
    align-items: center;
    border: 1px solid var(--rd-border);
    border-radius: 4px;
    overflow: hidden;
    margin-bottom: 1.5rem;
    font-family: var(--rd-font-code);
    font-size: 0.85rem;
  }

  .method {
    padding: 0.3rem 0.6rem;
    font-weight: 600;
    color: white;
  }

  .method.post { background-color: #2da44e; }
  .method.get { background-color: #0969da; }

  .path {
    padding: 0.3rem 0.6rem;
    background: rgba(128, 128, 128, 0.05);
    color: var(--rd-text-main);
  }

  /* Callouts */
  .callout {
    display: flex;
    gap: 0.75rem;
    padding: 1rem;
    border-radius: 4px;
    background: var(--rd-sidebar-bg);
    margin: 1.5rem 0;
    border: 1px solid var(--rd-border);
  }

  .callout-warning { border-left: 4px solid #d29922; }
  .callout-warning :global(svg) { color: #d29922; flex-shrink: 0; margin-top: 0.1rem; }
  .callout-info { border-left: 4px solid var(--rd-accent); }
  .callout-info :global(svg) { color: var(--rd-accent); flex-shrink: 0; margin-top: 0.1rem; }

  .callout strong { display: block; margin-bottom: 0.2rem; color: var(--rd-text-main); }
  .callout p { margin: 0; font-size: 0.9rem; color: var(--rd-text-muted); }

  /* Tables */
  .redoc-table {
    width: 100%;
    border-collapse: collapse;
    margin: 1.5rem 0;
    font-size: 0.9rem;
  }

  .redoc-table th,
  .redoc-table td {
    padding: 0.85rem 1rem;
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
    padding: 0.2rem 0.5rem;
    border-radius: 3px;
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.05em;
  }
  .active { background: rgba(46, 160, 67, 0.15); color: #3fb950; }
  .cooldown { background: rgba(210, 153, 34, 0.15); color: #d29922; }
  .invalid { background: rgba(248, 81, 73, 0.15); color: #f85149; }

  /* Code Panels (Right Side) */
  .code-panel {
    background: #0d1117; /* GitHub Dark Dimmed background */
    border-radius: 6px;
    border: 1px solid rgba(255, 255, 255, 0.1);
    position: relative;
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  }

  .code-header {
    background: rgba(255, 255, 255, 0.03);
    padding: 0.6rem 1rem;
    font-size: 0.75rem;
    color: #8b949e;
    border-bottom: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px 6px 0 0;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .code-panel pre {
    margin: 0;
    padding: 1.25rem 1rem;
    overflow-x: auto;
  }

  .code-panel code {
    font-family: var(--rd-font-code);
    font-size: 0.85rem;
    color: #c9d1d9; /* Light grey code */
    line-height: 1.5;
    background: transparent;
  }

  .copy-btn {
    position: absolute;
    top: 0.45rem;
    right: 0.5rem;
    background: transparent;
    border: none;
    color: #8b949e;
    cursor: pointer;
    padding: 0.3rem;
    border-radius: 4px;
    transition: color 0.15s, background 0.15s;
    display: inline-flex;
    align-items: center;
    justify-content: center;
  }

  .copy-btn:hover {
    color: #ffffff;
    background: rgba(255, 255, 255, 0.1);
  }

  .response-panel .code-header {
    color: #3fb950;
  }

  .api-footer {
    padding: 3rem;
    text-align: center;
    color: var(--rd-text-muted);
    font-size: 0.85rem;
    background: var(--rd-bg-text);
  }

  @media (max-width: 800px) {
    .redoc-sidebar {
      display: none;
    }
  }
</style>
