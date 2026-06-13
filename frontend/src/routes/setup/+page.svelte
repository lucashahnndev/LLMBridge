<script lang="ts">
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { fetchAdminSetupStatus, getStoredAdminToken, setupAdminPassword, setStoredAdminToken } from '$lib/api';
  import { applyThemeMode, getStoredThemeMode, setStoredThemeMode, type ThemeMode } from '$lib/theme';

  let password = '';
  let confirmPassword = '';
  let loading = false;
  let error = '';
  let info = '';
  let themeMode: ThemeMode = 'system';

  async function refreshSetupStatus() {
    try {
      const status = await fetchAdminSetupStatus();
      if (!status.setup_required) {
        await goto('/login');
        return true;
      }
    } catch {
      // If the status endpoint is unavailable, we still show the setup form.
    }

    return false;
  }

  async function handleSetup() {
    if (!password || !confirmPassword) {
      error = 'Preencha a senha e a confirmação.';
      return;
    }
    if (password !== confirmPassword) {
      error = 'As senhas não coincidem.';
      return;
    }

    loading = true;
    error = '';
    try {
      const result = await setupAdminPassword({ password, confirm_password: confirmPassword });
      setStoredAdminToken(result.access_token);
      await goto('/app');
    } catch (nextError) {
      error = nextError instanceof Error ? nextError.message : 'Falha ao concluir o setup.';
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

    void (async () => {
      const redirected = await refreshSetupStatus();
      if (!redirected) {
        info = 'Create the first admin password to unlock the dashboard.';
      }
    })();
  });
</script>

<svelte:head>
  <title>LLMBridge Setup</title>
  <meta name="description" content="LLMBridge initial admin password setup." />
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
        <h1>Initial setup</h1>
      </div>
      <p>Create the first admin password. If you later forget it, the `ADMIN_PASSWORD` env value can still act as recovery override.</p>
    </div>

    <div class="auth-panel">
      {#if info}
        <div class="inline-note">{info}</div>
      {/if}

      <form on:submit|preventDefault={handleSetup}>
        <label>
          Admin password
          <input bind:value={password} type="password" placeholder="Create a password" />
        </label>

        <label>
          Confirm password
          <input bind:value={confirmPassword} type="password" placeholder="Repeat the password" />
        </label>

        {#if error}
          <div class="inline-note error">{error}</div>
        {/if}

        <button type="submit" disabled={loading}>
          {loading ? 'Creating...' : 'Create password'}
        </button>
      </form>
    </div>
  </section>
</main>
