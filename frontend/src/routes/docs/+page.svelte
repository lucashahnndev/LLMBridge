<script lang="ts">
  import { onMount } from 'svelte';
  import {
    Copy,
    KeyRound,
    Layers3,
    PlugZap,
    Server,
    Settings2,
    ShieldCheck,
    WandSparkles
  } from 'lucide-svelte';

  type DocSection = {
    id: string;
    label: string;
    eyebrow: string;
    title: string;
    body: string;
  };

  type Snippet = {
    id: string;
    title: string;
    description: string;
    code: string;
    language: string;
  };

  const sections: DocSection[] = [
    {
      id: 'quickstart',
      eyebrow: 'Start here',
      title: 'Order of use',
      body:
        'Set the runtime, create your app token, register provider keys, then group them into queues. The proxy keeps the public contract stable while routing and rotating behind the scenes.'
    },
    {
      id: 'convention',
      eyebrow: 'Routing',
      title: 'Model convention',
      body:
        'Use direct routes for real provider/model pairs. Use queues when you want ordered fallback, smart ranking, or latency-aware routing.'
    },
    {
      id: 'claude-code',
      eyebrow: 'Client setup',
      title: 'Claude Code',
      body:
        'Point Claude Code to the gateway with Anthropic-compatible settings. The gateway accepts Anthropic-style traffic and normalizes the response shape for the provider behind the queue.'
    },
    {
      id: 'examples',
      eyebrow: 'Usage',
      title: 'Request examples',
      body:
        'The same gateway can serve OpenAI-like consumers and Anthropic-like consumers. Use the direct provider route when you want one model; use queue aliases when you want rotation and fallback.'
    },
    {
      id: 'ops',
      eyebrow: 'Operations',
      title: 'Run it safely',
      body:
        'Keep the service running as a single Linux or Windows service, restart it after runtime changes, and use the dashboard for the health and telemetry view.'
    }
  ];

  const snippets: Snippet[] = [
    {
      id: 'settings-json',
      title: 'VS Code / Claude Code settings',
      description:
        'Use this shape in the Claude Code settings file or in the VS Code integration settings that expose claudeCode.* keys.',
      language: 'json',
      code: `{
  "claudeCode.preferredLocation": "panel",
  "claudeCode.environmentVariables": [
    {
      "name": "ANTHROPIC_BASE_URL",
      "value": "http://127.0.0.1:8009"
    },
    {
      "name": "ANTHROPIC_AUTH_TOKEN",
      "value": "lk-key-I9rd48IM8vjUh_PsUTFEhFubh0rsq2R-"
    },
    {
      "name": "ANTHROPIC_MODEL",
      "value": "queue/gemini"
    }
  ]
}`
    },
    {
      id: 'direct-route',
      title: 'Direct provider route',
      description: 'Use the real provider/model path when you know the exact backend target.',
      language: 'bash',
      code: `POST /v1/chat/completions
{
  "model": "google/gemini-3.1-flash",
  "messages": [
    { "role": "user", "content": "Resuma este texto." }
  ]
}`
    },
    {
      id: 'queue-route',
      title: 'Queue route',
      description: 'Use a queue alias to let the proxy try models in the configured order or strategy.',
      language: 'bash',
      code: `POST /v1/messages
{
  "model": "queue/gemini",
  "messages": [
    { "role": "user", "content": "olá" }
  ]
}`
    }
  ];

  const quickSteps = [
    {
      title: 'Set the runtime',
      text: 'Confirm HOST and PORT in backend/.env, then start the service. The dashboard reads the runtime from the backend and shows the active base URL.'
    },
    {
      title: 'Create an app token',
      text: 'Use an app token for each consumer project. This is the public token clients send to the gateway.'
    },
    {
      title: 'Add provider keys',
      text: 'Register one or more keys per provider. The proxy rotates through eligible keys when a call fails or a key is in cooldown.'
    },
    {
      title: 'Build queues',
      text: 'Create queues when you want ordered fallback, smart ranking, or latency-aware routing across provider/model candidates.'
    }
  ];

  const queueStrategies = [
    {
      name: 'ordered',
      text: 'Always follows the candidate order from top to bottom.'
    },
    {
      name: 'smart',
      text: 'Re-ranks candidates using observed failures, latency, and success history.'
    },
    {
      name: 'latency',
      text: 'Prefers faster candidates when several are available.'
    }
  ];

  let copiedId = '';
  let copyError = '';

  async function copySnippet(snippet: Snippet) {
    copyError = '';
    try {
      await navigator.clipboard.writeText(snippet.code);
      copiedId = snippet.id;
      window.setTimeout(() => {
        if (copiedId === snippet.id) {
          copiedId = '';
        }
      }, 1800);
    } catch {
      copyError = 'Copy failed in this browser.';
    }
  }

  onMount(() => {
    document.documentElement.dataset.route = 'docs';
  });
</script>

<svelte:head>
  <title>LLMKeyRotator Docs</title>
  <meta
    name="description"
    content="Technical documentation for LLMKeyRotator, queue routing, provider keys, app tokens, and Claude Code setup."
  />
</svelte:head>

<main class="docs-shell">
  <aside class="docs-nav">
    <div class="docs-brand">
      <span class="docs-eyebrow">LLMKeyRotator</span>
      <h1>Docs</h1>
      <p>Technical usage guide for the gateway, queues, and client integrations.</p>
    </div>

    <nav>
      {#each sections as section}
        <a href={`#${section.id}`} class="docs-nav-link">
          <span>{section.eyebrow}</span>
          <strong>{section.title}</strong>
        </a>
      {/each}
    </nav>

    <div class="docs-side-note">
      <span class="docs-icon"><ShieldCheck size={16} /></span>
      <span>OpenAI-like output on the public proxy, Anthropic-like adapter at /v1/messages.</span>
    </div>
  </aside>

  <section class="docs-main">
    <header class="docs-hero">
      <div>
        <span class="docs-eyebrow">Control plane docs</span>
        <h2>Use the gateway in the right order.</h2>
        <p>
          This gateway is built around three primitives: app tokens, provider keys, and model queues.
          Configure the runtime first, then create the public token, then add provider credentials,
          and finally map them into queues for ordered fallback or smart routing.
        </p>
      </div>
      <div class="docs-hero-card">
        <div class="hero-stat">
          <span>Routes</span>
          <strong>provider/model · queue/name</strong>
        </div>
        <div class="hero-stat">
          <span>Protocols</span>
          <strong>OpenAI-like · Anthropic-like</strong>
        </div>
        <div class="hero-stat">
          <span>Focus</span>
          <strong>Rotation, fallback, telemetry</strong>
        </div>
      </div>
    </header>

    <section class="docs-panel" id="quickstart">
      <div class="panel-head">
        <span class="panel-eyebrow">Start here</span>
        <h3>Order of use</h3>
      </div>

      <div class="step-grid">
        {#each quickSteps as step, index}
          <article class="step-card">
            <span class="step-index">0{index + 1}</span>
            <h4>{step.title}</h4>
            <p>{step.text}</p>
          </article>
        {/each}
      </div>
    </section>

    <section class="docs-panel" id="convention">
      <div class="panel-head">
        <span class="panel-eyebrow">Routing</span>
        <h3>Model convention</h3>
      </div>

      <div class="convention-grid">
        <article class="callout">
          <span class="docs-icon"><Layers3 size={18} /></span>
          <div>
            <strong>Direct route</strong>
            <p>Use <code>provider/model</code> when you want a specific upstream model path.</p>
          </div>
        </article>
        <article class="callout">
          <span class="docs-icon"><WandSparkles size={18} /></span>
          <div>
            <strong>Queue route</strong>
            <p>Use <code>queue/name</code> when you want the proxy to try a configured list.</p>
          </div>
        </article>
      </div>

      <div class="queue-strategies">
        {#each queueStrategies as strategy}
          <article class="strategy-pill">
            <strong>{strategy.name}</strong>
            <span>{strategy.text}</span>
          </article>
        {/each}
      </div>
    </section>

    <section class="docs-panel" id="claude-code">
      <div class="panel-head">
        <span class="panel-eyebrow">Client setup</span>
        <h3>Claude Code</h3>
      </div>

      <p class="panel-text">
        Claude Code can point at the gateway through Anthropic-compatible settings. Use your app
        token as the auth token, and point the model at a queue alias so the proxy can rotate and
        fall back behind the scenes.
      </p>

      <div class="snippet-grid">
        {#each snippets.filter((snippet) => snippet.id === 'settings-json') as snippet}
          <article class="snippet-card">
            <div class="snippet-head">
              <div>
                <span>{snippet.language.toUpperCase()}</span>
                <h4>{snippet.title}</h4>
              </div>
              <button type="button" class="copy-btn" on:click={() => copySnippet(snippet)}>
                <Copy size={14} />
                {copiedId === snippet.id ? 'Copied' : 'Copy'}
              </button>
            </div>
            <p>{snippet.description}</p>
            <pre><code>{snippet.code}</code></pre>
          </article>
        {/each}
      </div>
    </section>

    <section class="docs-panel" id="examples">
      <div class="panel-head">
        <span class="panel-eyebrow">Usage</span>
        <h3>Request examples</h3>
      </div>

      <div class="snippet-grid">
        {#each snippets.filter((snippet) => snippet.id !== 'settings-json') as snippet}
          <article class="snippet-card">
            <div class="snippet-head">
              <div>
                <span>{snippet.language.toUpperCase()}</span>
                <h4>{snippet.title}</h4>
              </div>
              <button type="button" class="copy-btn" on:click={() => copySnippet(snippet)}>
                <Copy size={14} />
                {copiedId === snippet.id ? 'Copied' : 'Copy'}
              </button>
            </div>
            <p>{snippet.description}</p>
            <pre><code>{snippet.code}</code></pre>
          </article>
        {/each}
      </div>
    </section>

    <section class="docs-panel" id="ops">
      <div class="panel-head">
        <span class="panel-eyebrow">Operations</span>
        <h3>Run it safely</h3>
      </div>

      <div class="ops-grid">
        <article class="ops-card">
          <span class="docs-icon"><Server size={18} /></span>
          <strong>One service</strong>
          <p>Run backend and frontend together through the combined service launcher.</p>
        </article>
        <article class="ops-card">
          <span class="docs-icon"><Settings2 size={18} /></span>
          <strong>Restart after runtime changes</strong>
          <p>When host or port changes, save the runtime config and restart the service.</p>
        </article>
        <article class="ops-card">
          <span class="docs-icon"><KeyRound size={18} /></span>
          <strong>Token-first access</strong>
          <p>Use app tokens for consumers, provider keys for upstream credentials, and queues for routing.</p>
        </article>
        <article class="ops-card">
          <span class="docs-icon"><PlugZap size={18} /></span>
          <strong>Gateway contract</strong>
          <p>The proxy normalizes responses so clients can stay OpenAI-like or Anthropic-like.</p>
        </article>
      </div>

      {#if copyError}
        <p class="copy-error">{copyError}</p>
      {/if}
    </section>
  </section>
</main>

<style>
  :global(html[data-route='docs']) {
    color-scheme: light;
    scroll-behavior: smooth;
  }

  .docs-shell {
    min-height: 100vh;
    display: grid;
    grid-template-columns: 300px minmax(0, 1fr);
    background: #f6f8fa;
    color: #24292f;
  }

  .docs-nav {
    position: sticky;
    top: 0;
    height: 100vh;
    padding: 1.5rem 1.25rem;
    border-right: 1px solid #d0d7de;
    background: #ffffff;
    display: flex;
    flex-direction: column;
    gap: 1.2rem;
  }

  .docs-brand {
    padding-bottom: 1rem;
    border-bottom: 1px solid #d8dee4;
  }

  .docs-brand h1,
  .docs-hero h2,
  .panel-head h3 {
    margin: 0;
    line-height: 1.1;
  }

  .docs-brand h1 {
    margin-top: 0.35rem;
    font-size: 1.5rem;
  }

  .docs-brand p,
  .docs-hero p,
  .panel-text,
  .step-card p,
  .callout p,
  .ops-card p,
  .snippet-card p {
    color: #57606a;
  }

  .docs-nav nav {
    display: grid;
    gap: 0.5rem;
  }

  .docs-nav-link {
    display: grid;
    gap: 0.2rem;
    padding: 0.9rem 1rem;
    border: 1px solid #d8dee4;
    border-radius: 6px;
    text-decoration: none;
    background: #ffffff;
  }

  .docs-nav-link span,
  .docs-eyebrow,
  .panel-eyebrow {
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.16em;
    color: #0969da;
  }

  .docs-nav-link strong {
    font-size: 0.98rem;
    font-weight: 600;
  }

  .docs-side-note {
    margin-top: auto;
    display: flex;
    gap: 0.75rem;
    align-items: flex-start;
    padding: 0.9rem 1rem;
    border: 1px solid #d8dee4;
    border-radius: 6px;
    background: #f6f8fa;
    color: #57606a;
  }

  .docs-main {
    padding: 2rem 2rem 3rem;
    display: grid;
    gap: 1.25rem;
    align-content: start;
    max-width: 1200px;
    width: 100%;
    margin: 0 auto;
  }

  .docs-hero,
  .docs-panel {
    border: 1px solid #d8dee4;
    border-radius: 6px;
    background: #ffffff;
  }

  .docs-hero {
    display: grid;
    grid-template-columns: minmax(0, 1.5fr) minmax(260px, 0.75fr);
    gap: 1rem;
    padding: 1.25rem;
  }

  .docs-hero h2 {
    margin-top: 0.35rem;
    font-size: clamp(2rem, 3vw, 2.8rem);
    max-width: 10ch;
  }

  .docs-hero p {
    max-width: 72ch;
    margin-bottom: 0;
  }

  .docs-hero-card {
    display: grid;
    gap: 0.75rem;
    padding: 1rem;
    border: 1px solid #d8dee4;
    border-radius: 6px;
    background: #f6f8fa;
  }

  .hero-stat {
    display: grid;
    gap: 0.15rem;
    padding-bottom: 0.7rem;
    border-bottom: 1px solid #d8dee4;
  }

  .hero-stat:last-child {
    padding-bottom: 0;
    border-bottom: 0;
  }

  .hero-stat span {
    color: #57606a;
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.12em;
  }

  .panel-head {
    display: grid;
    gap: 0.25rem;
    padding: 1rem 1.25rem 0.85rem;
    border-bottom: 1px solid #d8dee4;
  }

  .panel-head h3 {
    font-size: 1.2rem;
  }

  .step-grid,
  .convention-grid,
  .snippet-grid,
  .ops-grid {
    display: grid;
    gap: 0.85rem;
    padding: 1rem 1.25rem 1.25rem;
  }

  .step-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }

  .step-card,
  .callout,
  .strategy-pill,
  .snippet-card,
  .ops-card {
    border: 1px solid #d8dee4;
    border-radius: 6px;
    background: #ffffff;
  }

  .step-card,
  .callout,
  .strategy-pill,
  .ops-card {
    padding: 0.95rem 1rem;
  }

  .step-index {
    display: inline-flex;
    width: fit-content;
    margin-bottom: 0.5rem;
    padding: 0.18rem 0.45rem;
    border: 1px solid #d0d7de;
    border-radius: 999px;
    color: #0969da;
    font-size: 0.72rem;
    letter-spacing: 0.12em;
  }

  .step-card h4,
  .ops-card strong,
  .callout strong,
  .strategy-pill strong {
    margin: 0 0 0.35rem;
    font-size: 1rem;
  }

  .step-card p,
  .callout p,
  .strategy-pill span,
  .ops-card p {
    margin: 0;
  }

  .convention-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .callout {
    display: flex;
    gap: 0.85rem;
    align-items: flex-start;
  }

  .docs-icon {
    display: inline-flex;
    flex: none;
    color: #0969da;
    margin-top: 0.2rem;
  }

  .queue-strategies {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.75rem;
    padding: 0 1.25rem 1.25rem;
  }

  .strategy-pill strong {
    display: block;
    text-transform: lowercase;
  }

  .panel-text {
    margin: 0;
    padding: 1rem 1.25rem 0;
  }

  .snippet-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .snippet-card {
    overflow: hidden;
  }

  .snippet-head {
    display: flex;
    justify-content: space-between;
    gap: 0.75rem;
    align-items: flex-start;
    padding: 1rem 1rem 0.75rem;
    border-bottom: 1px solid #d8dee4;
  }

  .snippet-head h4 {
    margin: 0.15rem 0 0;
    font-size: 1rem;
  }

  .snippet-head span {
    color: #57606a;
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.12em;
  }

  .snippet-card p {
    margin: 0;
    padding: 0.85rem 1rem 0;
  }

  .snippet-card pre {
    margin: 0;
    padding: 1rem;
    overflow: auto;
    font-size: 0.87rem;
    line-height: 1.55;
    background: #f6f8fa;
    border-top: 1px solid #d8dee4;
  }

  .snippet-card code {
    font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  }

  .copy-btn {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    padding: 0.5rem 0.75rem;
    border-radius: 6px;
    font-size: 0.82rem;
    background: #ffffff;
    border: 1px solid #d0d7de;
  }

  .ops-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .ops-card {
    display: grid;
    gap: 0.45rem;
  }

  .copy-error {
    margin: 0;
    padding: 0 1.25rem 1.25rem;
    color: #cf222e;
  }

  @media (max-width: 1180px) {
    .docs-shell {
      grid-template-columns: 1fr;
    }

    .docs-nav {
      position: relative;
      height: auto;
      border-right: 0;
      border-bottom: 1px solid #d8dee4;
    }

    .docs-hero,
    .step-grid,
    .convention-grid,
    .queue-strategies,
    .snippet-grid,
    .ops-grid {
      grid-template-columns: 1fr;
    }
  }

  @media (max-width: 720px) {
    .docs-main {
      padding: 1rem;
    }

    .docs-hero {
      padding: 1rem;
    }

    .panel-head,
    .panel-text,
    .step-grid,
    .convention-grid,
    .snippet-grid,
    .ops-grid {
      padding-left: 1rem;
      padding-right: 1rem;
    }

    .queue-strategies {
      padding: 0 1rem 1rem;
    }
  }
</style>
