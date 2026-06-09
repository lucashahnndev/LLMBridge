<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { fetchHealth, getStoredAdminToken, loginAdmin, setStoredAdminToken, type HealthResponse } from '$lib/api';
  import { applyThemeMode, getStoredThemeMode, setStoredThemeMode, type ThemeMode } from '$lib/theme';
  import { ShieldCheck } from 'lucide-svelte';

  let password = '';
  let loading = false;
  let error = '';
  let backendHealth: HealthResponse | null = null;
  let healthError = '';
  let themeMode: ThemeMode = 'system';

  async function refreshHealth() {
    healthError = '';
    try {
      backendHealth = await fetchHealth();
    } catch (nextError) {
      backendHealth = null;
      healthError = nextError instanceof Error ? nextError.message : 'Health check failed';
    }
  }

  async function handleLogin() {
    if (!password) {
      error = 'Enter the admin password.';
      return;
    }

    loading = true;
    error = '';
    try {
      const result = await loginAdmin(password);
      setStoredAdminToken(result.access_token);
      await goto('/app');
    } catch (nextError) {
      error = nextError instanceof Error ? nextError.message : 'Login failed';
    } finally {
      loading = false;
    }
  }

  function handleThemeModeChange() {
    setStoredThemeMode(themeMode);
    applyThemeMode(themeMode);
  }

  onMount(() => {
    themeMode = getStoredThemeMode();
    applyThemeMode(themeMode);

    if (getStoredAdminToken()) {
      void goto('/app');
      return;
    }

    void refreshHealth();
  });
</script>

<svelte:head>
  <title>LLMBridge Login</title>
  <meta
    name="description"
    content="Enter the admin console for the local LLM gateway and key rotator."
  />
</svelte:head>

<main class="auth-shell">
  <div class="auth-toolbar">
    <label class="theme-control">
      <select bind:value={themeMode} on:change={handleThemeModeChange}>
        <option value="system">System Mode</option>
        <option value="dark">Dark Mode</option>
        <option value="light">Light Mode</option>
      </select>
    </label>
  </div>

  <section class="auth-card">
    <div class="auth-copy">
      <div style="display: flex; gap: 0.75rem; align-items: center; margin-bottom: 1rem;">
        <ShieldCheck size={32} color="var(--accent)" />
      </div>
      <span class="eyebrow">LLMBridge</span>
      <h1>Console access</h1>
      <p>Local operator sign-in.</p>
    </div>

    <div class="auth-panel">
      <div class="health-row">
        <span>Backend</span>
        <strong>{backendHealth ? `${backendHealth.service} ${backendHealth.status}` : 'Unknown'}</strong>
      </div>
      {#if healthError}
        <div class="inline-note error">{healthError}</div>
      {/if}

      <form on:submit|preventDefault={handleLogin}>
        <label>
          Admin password
          <input bind:value={password} type="password" placeholder="Enter admin password" />
        </label>

        {#if error}
          <div class="inline-note error">{error}</div>
        {/if}

        <button type="submit" disabled={loading}>
          {loading ? '...' : 'Enter'}
        </button>
      </form>

      <p class="fineprint">Local only.</p>
    </div>
  </section>
</main>
