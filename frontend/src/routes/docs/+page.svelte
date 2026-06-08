<script lang="ts">
  import { onMount } from 'svelte';
  import { Copy, Terminal, CheckCircle2, AlertCircle, Info, BookOpen } from 'lucide-svelte';

  type Snippet = {
    id: string;
    code: string;
  };

  let copiedId = '';

  async function copySnippet(snippet: Snippet) {
    try {
      await navigator.clipboard.writeText(snippet.code);
      copiedId = snippet.id;
      window.setTimeout(() => {
        if (copiedId === snippet.id) {
          copiedId = '';
        }
      }, 2000);
    } catch {
      // fallback handling if needed
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

  onMount(() => {
    // Allows highlighting or smooth scrolling
  });
</script>

<svelte:head>
  <title>LLMKeyRotator Documentation</title>
</svelte:head>

<div class="docs-layout">
  <aside class="docs-sidebar">
    <div class="sidebar-header">
      <BookOpen size={20} />
      <span>LLMKeyRotator</span>
    </div>
    <nav class="sidebar-nav">
      <div class="nav-group">
        <strong>Getting Started</strong>
        <a href="#overview">Overview</a>
        <a href="#quickstart">Quickstart</a>
        <a href="#runtime-setup">Runtime Setup</a>
      </div>
      <div class="nav-group">
        <strong>Core Concepts</strong>
        <a href="#app-tokens">App Tokens</a>
        <a href="#provider-keys">Provider Keys</a>
        <a href="#queues">Queues & Routing</a>
      </div>
      <div class="nav-group">
        <strong>API Reference</strong>
        <a href="#authentication">Authentication</a>
        <a href="#endpoints">Endpoints</a>
        <a href="#examples">Examples</a>
      </div>
      <div class="nav-group">
        <strong>Operations</strong>
        <a href="#errors">Errors & Troubleshooting</a>
        <a href="#telemetry">Telemetry & Limits</a>
      </div>
    </nav>
  </aside>

  <main class="docs-content">
    <div class="content-wrapper">
      <h1 id="overview">Documentation</h1>
      <p class="lead">
        LLMKeyRotator is an AI API Gateway designed to stabilize upstream provider APIs. It acts as a middle layer, receiving requests from your applications and routing them to external providers with built-in failover, load balancing, and rotation logic.
      </p>

      <hr />

      <h2 id="quickstart">Quickstart</h2>
      <p>To start routing requests through the gateway, follow this strict sequence of operations in the Admin Dashboard:</p>
      
      <ol class="docs-list">
        <li><strong>Configure runtime:</strong> Set the backend host and port in the runtime config and ensure the service is running.</li>
        <li><strong>Create an App Token:</strong> Generate a token for your client applications to authenticate against the gateway.</li>
        <li><strong>Add Provider Keys:</strong> Register upstream API keys (e.g., OpenAI, Google, OpenRouter).</li>
        <li><strong>Create Queues:</strong> Group your models into logical queues (e.g., <code>production</code>) to enable ordered fallback and automatic rotation.</li>
        <li><strong>Send Requests:</strong> Point your client code to the gateway URL using your App Token and target your queue alias.</li>
      </ol>

      <hr />

      <h2 id="runtime-setup">Runtime Setup</h2>
      <p>
        The gateway consists of a frontend administrative dashboard and a backend API engine. The backend must be bound to a local or public host.
      </p>
      <div class="callout callout-info">
        <Info size={18} />
        <div>
          <strong>Restart Required</strong>
          <p>If you modify the Host or Port settings in the Runtime section of the dashboard, you must restart the backend process for the changes to take effect at the socket level.</p>
        </div>
      </div>

      <hr />

      <h2 id="app-tokens">App Tokens</h2>
      <p>
        App Tokens represent your downstream clients (e.g., an internal service, a mobile app, or Claude Code). 
        These tokens must be included in the <code>Authorization: Bearer &lt;token&gt;</code> header of every request made to the gateway.
      </p>
      <ul>
        <li>Tokens can be temporarily disabled.</li>
        <li>Tokens can be constrained with strict <strong>Rate Limits (RPM)</strong>.</li>
        <li>Tokens only exist in the database and must be safely distributed to your consumers.</li>
      </ul>

      <hr />

      <h2 id="provider-keys">Provider Keys</h2>
      <p>
        Provider keys are your actual billing credentials for upstream AI providers (OpenAI, Anthropic, Google, OpenRouter). 
        The gateway securely holds these keys and injects them into downstream requests.
      </p>
      <table class="docs-table">
        <thead>
          <tr>
            <th>Provider State</th>
            <th>Behavior</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><span class="status-badge status-active">ACTIVE</span></td>
            <td>Key is healthy and available for routing.</td>
          </tr>
          <tr>
            <td><span class="status-badge status-cooldown">COOLDOWN</span></td>
            <td>Key is temporarily suspended due to 429 Too Many Requests or 500 errors.</td>
          </tr>
          <tr>
            <td><span class="status-badge status-invalid">INVALID</span></td>
            <td>Key returned a 401/403. It will not be used until manually verified.</td>
          </tr>
          <tr>
            <td><span class="status-badge status-suspended">SUSPENDED_BILLING</span></td>
            <td>Provider rejected the key due to missing funds or quota limits.</td>
          </tr>
        </tbody>
      </table>

      <hr />

      <h2 id="queues">Queues & Routing</h2>
      <p>
        Queues map an abstract model target (e.g., <code>queue/production</code>) to an ordered list of real models. 
        When a request is sent to a queue, the gateway tries the candidates in sequence.
      </p>

      <h3>Routing Patterns</h3>
      <table class="docs-table">
        <thead>
          <tr>
            <th>Pattern</th>
            <th>Format</th>
            <th>Use Case</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>Direct Route</strong></td>
            <td><code>provider/model_name</code></td>
            <td>Target a specific provider unconditionally (e.g., <code>google/gemini-1.5-pro</code>). Fails directly if the provider errors.</td>
          </tr>
          <tr>
            <td><strong>Queue Route</strong></td>
            <td><code>queue/queue_name</code></td>
            <td>Target a managed queue. Evaluates candidates based on the queue strategy and fails over automatically.</td>
          </tr>
        </tbody>
      </table>

      <h3>Queue Strategies</h3>
      <ul>
        <li><strong>ordered:</strong> Iterates over candidates strictly by their configured position (e.g., 0, 1, 2).</li>
        <li><strong>smart:</strong> Penalizes candidates with high failure rates dynamically to ensure maximum uptime.</li>
        <li><strong>latency:</strong> Prefers candidates that historically respond faster.</li>
      </ul>

      <hr />

      <h2 id="authentication">Authentication</h2>
      <p>The API expects an App Token provided as a Bearer token in the Authorization header.</p>
      
      <div class="code-block">
        <div class="code-header">
          <span>Header</span>
        </div>
        <pre><code>Authorization: Bearer your-app-token-here</code></pre>
      </div>

      <div class="callout callout-warning">
        <AlertCircle size={18} />
        <div>
          <strong>Missing or invalid token</strong>
          <p>Failing to provide a valid, active App Token will immediately result in a <code>401 Unauthorized</code> response.</p>
        </div>
      </div>

      <hr />

      <h2 id="endpoints">Endpoints</h2>
      
      <h3>Anthropic Protocol</h3>
      <p><code>POST /v1/messages</code></p>
      <p>The gateway implements the Anthropic <code>/v1/messages</code> standard. It acts as an adapter, parsing Anthropic payloads and normalizing the responses from OpenAI, Google, or OpenRouter behind the scenes.</p>

      <h3>OpenAI Protocol</h3>
      <p><code>POST /v1/chat/completions</code></p>
      <p>Provides a native OpenAI-compatible API interface. Downstream providers are translated back into the OpenAI schema.</p>

      <hr />

      <h2 id="examples">Examples</h2>

      <h3>cURL Example</h3>
      <div class="code-block">
        <div class="code-header">
          <span>bash</span>
          <button on:click={() => copySnippet({ id: 'curl', code: curlExample })} class="copy-btn">
            {#if copiedId === 'curl'}<CheckCircle2 size={14} />{:else}<Copy size={14} />{/if}
            {copiedId === 'curl' ? 'Copied' : 'Copy'}
          </button>
        </div>
        <pre><code>{curlExample}</code></pre>
      </div>

      <h3>Node.js / Fetch</h3>
      <div class="code-block">
        <div class="code-header">
          <span>javascript</span>
          <button on:click={() => copySnippet({ id: 'js', code: jsExample })} class="copy-btn">
            {#if copiedId === 'js'}<CheckCircle2 size={14} />{:else}<Copy size={14} />{/if}
            {copiedId === 'js' ? 'Copied' : 'Copy'}
          </button>
        </div>
        <pre><code>{jsExample}</code></pre>
      </div>

      <h3>Claude Code Integration</h3>
      <p>To use LLMKeyRotator as your backend for Claude Code, update your Claude Code settings profile to point the Base URL to the Gateway.</p>
      <div class="code-block">
        <div class="code-header">
          <span>json</span>
          <button on:click={() => copySnippet({ id: 'json', code: claudeCodeSettings })} class="copy-btn">
            {#if copiedId === 'json'}<CheckCircle2 size={14} />{:else}<Copy size={14} />{/if}
            {copiedId === 'json' ? 'Copied' : 'Copy'}
          </button>
        </div>
        <pre><code>{claudeCodeSettings}</code></pre>
      </div>

      <hr />

      <h2 id="errors">Errors & Troubleshooting</h2>
      <p>The gateway intercepts standard provider errors and implements failover. If all candidates fail, or if a direct route fails, the gateway surfaces the error.</p>
      
      <table class="docs-table">
        <thead>
          <tr>
            <th>Status Code</th>
            <th>Gateway Meaning</th>
            <th>Resolution</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td><strong>400</strong></td>
            <td>Bad Request</td>
            <td>The payload structure was malformed or unsupported.</td>
          </tr>
          <tr>
            <td><strong>401</strong></td>
            <td>Unauthorized</td>
            <td>Missing or invalid App Token.</td>
          </tr>
          <tr>
            <td><strong>403</strong></td>
            <td>Forbidden</td>
            <td>App token is disabled or unauthorized.</td>
          </tr>
          <tr>
            <td><strong>404</strong></td>
            <td>Not Found</td>
            <td>The specified queue or direct provider does not exist.</td>
          </tr>
          <tr>
            <td><strong>429</strong></td>
            <td>Too Many Requests</td>
            <td>Your App Token hit its configured RPM limit, or all providers are exhausted.</td>
          </tr>
          <tr>
            <td><strong>502</strong></td>
            <td>Bad Gateway</td>
            <td>Queue routing failed. All candidates in the queue were exhausted or timed out.</td>
          </tr>
        </tbody>
      </table>

      <hr />

      <h2 id="telemetry">Telemetry & Limits</h2>
      <p>
        The gateway passively tracks usage across all requests.
        You can view Real-time Traffic, Latency averages, and Total Token consumption in the Admin Dashboard's <strong>Overview</strong> and <strong>Usage</strong> pages.
      </p>
      <ul>
        <li><strong>App Token Quotas:</strong> Restrict traffic by assigning RPM (Requests Per Minute). Exceeding this limit immediately short-circuits the request with a 429.</li>
        <li><strong>Key Cooldowns:</strong> The proxy isolates failing keys. If a key returns a 429, it enters a cooldown phase and is bypassed on subsequent requests.</li>
      </ul>
      
      <div class="spacer"></div>
    </div>
  </main>
</div>

<style>
  /* Base Variables */
  :root {
    --doc-bg: #ffffff;
    --doc-sidebar-bg: #f8f9fa;
    --doc-text: #202124;
    --doc-text-muted: #5f6368;
    --doc-border: #e0e0e0;
    --doc-border-light: #f1f3f4;
    --doc-accent: #0f52ba; /* A serious, technical blue */
    --doc-accent-hover: #0a3d8f;
    --doc-code-bg: #f1f3f4;
    --doc-code-text: #202124;
    --doc-code-block-bg: #1e1e1e;
    --doc-code-block-text: #d4d4d4;
    --doc-table-head-bg: #f8f9fa;
    --doc-radius: 6px;
    --doc-max-width: 860px;
  }

  /* Dark Mode Support via media query */
  @media (prefers-color-scheme: dark) {
    :root {
      --doc-bg: #0d1117;
      --doc-sidebar-bg: #161b22;
      --doc-text: #c9d1d9;
      --doc-text-muted: #8b949e;
      --doc-border: #30363d;
      --doc-border-light: #21262d;
      --doc-accent: #58a6ff;
      --doc-accent-hover: #79c0ff;
      --doc-code-bg: rgba(110, 118, 129, 0.4);
      --doc-code-text: #c9d1d9;
      --doc-code-block-bg: #0d1117;
      --doc-code-block-text: #c9d1d9;
      --doc-table-head-bg: #161b22;
    }
  }

  /* Global Reset & Layout */
  :global(body[data-route="docs"]) {
    background-color: var(--doc-bg);
    color: var(--doc-text);
  }

  .docs-layout {
    display: flex;
    min-height: 100vh;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen, Ubuntu, Cantarell, "Open Sans", "Helvetica Neue", sans-serif;
    line-height: 1.6;
    background: var(--doc-bg);
    color: var(--doc-text);
  }

  /* Sidebar */
  .docs-sidebar {
    width: 280px;
    flex-shrink: 0;
    background: var(--doc-sidebar-bg);
    border-right: 1px solid var(--doc-border);
    position: sticky;
    top: 0;
    height: 100vh;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
  }

  .sidebar-header {
    padding: 1.5rem;
    display: flex;
    align-items: center;
    gap: 0.75rem;
    font-weight: 600;
    font-size: 1.1rem;
    color: var(--doc-text);
    border-bottom: 1px solid var(--doc-border);
  }

  .sidebar-nav {
    padding: 1.5rem 1rem;
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
  }

  .nav-group {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .nav-group strong {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--doc-text-muted);
    margin-bottom: 0.25rem;
    padding-left: 0.5rem;
  }

  .nav-group a {
    text-decoration: none;
    color: var(--doc-text);
    font-size: 0.9rem;
    padding: 0.4rem 0.5rem;
    border-radius: var(--doc-radius);
    transition: background 0.15s, color 0.15s;
  }

  .nav-group a:hover {
    background: var(--doc-border-light);
    color: var(--doc-accent);
  }

  /* Main Content */
  .docs-content {
    flex-grow: 1;
    padding: 3rem 2rem;
    overflow-x: hidden;
  }

  .content-wrapper {
    max-width: var(--doc-max-width);
    margin: 0 auto;
  }

  /* Typography */
  h1, h2, h3 {
    color: var(--doc-text);
    font-weight: 600;
    margin-top: 2.5rem;
    margin-bottom: 1rem;
    line-height: 1.3;
  }

  h1 { font-size: 2.2rem; margin-top: 0; }
  h2 { font-size: 1.6rem; border-bottom: 1px solid var(--doc-border-light); padding-bottom: 0.5rem; }
  h3 { font-size: 1.2rem; margin-top: 2rem; }

  p {
    margin-top: 0;
    margin-bottom: 1rem;
    color: var(--doc-text);
  }

  .lead {
    font-size: 1.15rem;
    color: var(--doc-text-muted);
    margin-bottom: 2rem;
  }

  hr {
    border: 0;
    height: 1px;
    background: var(--doc-border);
    margin: 3rem 0;
  }

  .spacer {
    height: 4rem;
  }

  /* Lists */
  ul, ol {
    margin-top: 0;
    margin-bottom: 1.5rem;
    padding-left: 1.5rem;
    color: var(--doc-text);
  }

  li {
    margin-bottom: 0.5rem;
  }

  .docs-list li {
    padding-left: 0.25rem;
  }

  /* Inline Code */
  code {
    background: var(--doc-code-bg);
    color: var(--doc-code-text);
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    font-size: 0.85em;
    padding: 0.2em 0.4em;
    border-radius: 3px;
  }

  /* Code Blocks */
  .code-block {
    background: var(--doc-code-block-bg);
    border: 1px solid var(--doc-border);
    border-radius: var(--doc-radius);
    overflow: hidden;
    margin-bottom: 1.5rem;
    box-shadow: 0 4px 6px rgba(0,0,0,0.05);
  }

  .code-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 0.5rem 1rem;
    background: rgba(0, 0, 0, 0.2);
    border-bottom: 1px solid rgba(255, 255, 255, 0.1);
  }

  .code-header span {
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #8b949e;
    font-weight: 600;
  }

  .copy-btn {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    background: transparent;
    border: 1px solid rgba(255,255,255,0.2);
    color: #c9d1d9;
    padding: 0.3rem 0.6rem;
    border-radius: 4px;
    font-size: 0.75rem;
    cursor: pointer;
    transition: background 0.15s, border-color 0.15s;
  }

  .copy-btn:hover {
    background: rgba(255, 255, 255, 0.1);
    border-color: rgba(255,255,255,0.4);
  }

  .code-block pre {
    margin: 0;
    padding: 1rem;
    overflow-x: auto;
  }

  .code-block code {
    background: transparent;
    color: var(--doc-code-block-text);
    padding: 0;
    font-size: 0.85rem;
    border-radius: 0;
    line-height: 1.5;
  }

  /* Tables */
  .docs-table {
    width: 100%;
    border-collapse: collapse;
    margin-bottom: 1.5rem;
    font-size: 0.9rem;
  }

  .docs-table th,
  .docs-table td {
    padding: 0.75rem 1rem;
    border: 1px solid var(--doc-border);
    text-align: left;
  }

  .docs-table th {
    background: var(--doc-table-head-bg);
    font-weight: 600;
    color: var(--doc-text);
  }

  /* Status Badges */
  .status-badge {
    display: inline-flex;
    align-items: center;
    padding: 0.15rem 0.4rem;
    border-radius: 3px;
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.05em;
  }

  .status-active { background: rgba(46, 160, 67, 0.15); color: #3fb950; border: 1px solid rgba(46, 160, 67, 0.4); }
  .status-cooldown { background: rgba(210, 153, 34, 0.15); color: #d29922; border: 1px solid rgba(210, 153, 34, 0.4); }
  .status-invalid { background: rgba(248, 81, 73, 0.15); color: #f85149; border: 1px solid rgba(248, 81, 73, 0.4); }
  .status-suspended { background: rgba(139, 148, 158, 0.15); color: #8b949e; border: 1px solid rgba(139, 148, 158, 0.4); }

  /* Callouts */
  .callout {
    display: flex;
    gap: 1rem;
    padding: 1rem 1.25rem;
    border-radius: var(--doc-radius);
    border: 1px solid var(--doc-border);
    margin-bottom: 1.5rem;
    background: var(--doc-sidebar-bg);
  }

  .callout-info {
    border-left: 4px solid var(--doc-accent);
  }
  
  .callout-info :global(svg) {
    color: var(--doc-accent);
    margin-top: 0.15rem;
    flex-shrink: 0;
  }

  .callout-warning {
    border-left: 4px solid #d29922;
  }

  .callout-warning :global(svg) {
    color: #d29922;
    margin-top: 0.15rem;
    flex-shrink: 0;
  }

  .callout strong {
    display: block;
    font-size: 0.95rem;
    margin-bottom: 0.25rem;
    color: var(--doc-text);
  }

  .callout p {
    margin: 0;
    font-size: 0.9rem;
    color: var(--doc-text-muted);
  }

  /* Responsive */
  @media (max-width: 900px) {
    .docs-layout {
      flex-direction: column;
    }

    .docs-sidebar {
      width: 100%;
      height: auto;
      position: relative;
      border-right: none;
      border-bottom: 1px solid var(--doc-border);
    }
    
    .sidebar-nav {
      flex-direction: row;
      flex-wrap: wrap;
      gap: 1rem 2rem;
    }

    .docs-content {
      padding: 2rem 1.5rem;
    }
  }
</style>
