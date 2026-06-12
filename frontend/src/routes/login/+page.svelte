<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { fetchHealth, getStoredAdminToken, loginAdmin, setStoredAdminToken } from '$lib/api';
  import { applyThemeMode, getStoredThemeMode, setStoredThemeMode, type ThemeMode } from '$lib/theme';

  let password = '';
  let loading = false;
  let error = '';
  let healthError = '';
  let themeMode: ThemeMode = 'system';

  async function refreshHealth() {
    healthError = '';
    try {
      await fetchHealth();
    } catch (nextError) {
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
  <title>LLMBridge</title>
  <meta
    name="description"
    content="LLMBridge local gateway console."
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
      <div class="brand-lockup">
        <div class="brand-rule"></div>
        <h1>LLMBridge</h1>
      </div>
      <p>Local gateway control, without the clutter.</p>
    </div>

    <div class="auth-panel">
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

    </div>
  </section>
</main>
