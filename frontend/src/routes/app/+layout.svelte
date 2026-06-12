<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { clearStoredAdminToken, getStoredAdminToken, logoutAdmin } from '$lib/api';
  import { applyThemeMode, getStoredThemeMode, setStoredThemeMode, type ThemeMode } from '$lib/theme';
  import { activeSection, topbarTitle, refreshTrigger, sidebarCollapsed, type SectionKey } from '$lib/stores';
  import {
    LayoutDashboard,
    Key,
    Coins,
    BarChart2,
    Settings,
    PanelLeftClose,
    PanelLeftOpen,
    BookOpenText,
    SquareTerminal
  } from 'lucide-svelte';

  let token = '';
  let themeMode: ThemeMode = 'system';
  let isMounted = false;

  const sections: Array<{ key: SectionKey; label: string; icon: typeof LayoutDashboard }> = [
    { key: 'overview', label: 'Overview', icon: LayoutDashboard },
    { key: 'keys', label: 'Provider Keys', icon: Key },
    { key: 'tokens', label: 'App Tokens', icon: Coins },
    { key: 'queues', label: 'Model Queues', icon: BarChart2 },
    { key: 'usage', label: 'Usage', icon: BarChart2 },
    { key: 'runtime', label: 'Runtime', icon: Settings }
  ];

  async function handleLogout() {
    if (token) {
      try {
        await logoutAdmin(token);
      } catch {
        // If the backend is already unavailable or the token expired,
        // we still end the local session.
      }
    }

    clearStoredAdminToken();
    token = '';
    void goto('/login');
  }

  function triggerRefresh() {
    refreshTrigger.update((n) => n + 1);
  }

  function handleThemeModeChange() {
    setStoredThemeMode(themeMode);
    applyThemeMode(themeMode);
  }

  function handleNavClick(key: SectionKey) {
    activeSection.set(key);
    if ($page.url.pathname !== '/app') {
      void goto('/app');
    }
  }

  onMount(() => {
    const savedToken = getStoredAdminToken();
    if (!savedToken) {
      void goto('/login');
      return;
    }
    token = savedToken;
    themeMode = getStoredThemeMode();
    applyThemeMode(themeMode);
    isMounted = true;
  });
</script>

{#if isMounted}
  <main class="shell" class:sidebar-collapsed={$sidebarCollapsed}>
    <aside class="sidebar">
      <div class="brand">
        {#if $sidebarCollapsed}
          <div class="brand-icon">LB</div>
        {:else}
          <div class="eyebrow">LLMBridge</div>
          <h1>Control plane</h1>
        {/if}
      </div>

      <nav class="nav">
        {#each sections as section}
          <button
            type="button"
            class:active={$page.url.pathname === '/app' && $activeSection === section.key}
            on:click={() => handleNavClick(section.key)}
            title={$sidebarCollapsed ? section.label : ''}
          >
            <span class="nav-icon"><svelte:component this={section.icon} size={15} strokeWidth={1.6} /></span>
            {#if !$sidebarCollapsed}
              <span class="nav-label">{section.label}</span>
            {/if}
          </button>
        {/each}
        <button
          type="button"
          class:active={$page.url.pathname === '/app/playground'}
          on:click={() => goto('/app/playground')}
          title={$sidebarCollapsed ? 'Playground' : ''}
        >
          <span class="nav-icon"><SquareTerminal size={15} strokeWidth={1.6} /></span>
          {#if !$sidebarCollapsed}
            <span class="nav-label">Playground</span>
          {/if}
        </button>
      </nav>

      <div class="sidebar-footer">
        <button class="collapse-btn" on:click={() => sidebarCollapsed.set(!$sidebarCollapsed)} title={$sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}>
          <span class="nav-icon">
            {#if $sidebarCollapsed}
              <PanelLeftOpen size={15} strokeWidth={1.6} />
            {:else}
              <PanelLeftClose size={15} strokeWidth={1.6} />
            {/if}
          </span>
          {#if !$sidebarCollapsed}
            <span class="nav-label">Collapse</span>
          {/if}
        </button>
      </div>
    </aside>

    <section class="workspace">
      <header class="topbar">
        <div class="topbar-left">
          <span class="topbar-section">{$topbarTitle}</span>
        </div>
        <div class="topbar-tools">
          <button type="button" class="ghost icon-only" title="Documentation" aria-label="Open documentation" on:click={() => goto('/docs')}>
            <BookOpenText size={16} strokeWidth={1.8} />
          </button>
          <div class="topbar-divider"></div>
          <details class="profile-menu">
            <summary class="profile-summary">
              <span class="profile-avatar">A</span>
              <span class="profile-name">Administrator</span>
            </summary>
            <div class="profile-popover">
              <div class="popover-header">
                <span class="popover-avatar">A</span>
                <div class="popover-id">
                  <strong>Administrator</strong>
                  <small>{token ? 'Local session active' : 'No active session'}</small>
                </div>
              </div>
              <div class="popover-divider"></div>
              <div class="theme-switcher">
                <span class="theme-label">Appearance</span>
                <div class="theme-options">
                  <button type="button" class="theme-opt" class:theme-opt-active={themeMode === 'light'} on:click={() => { themeMode = 'light'; handleThemeModeChange(); }} title="Light">☀</button>
                  <button type="button" class="theme-opt" class:theme-opt-active={themeMode === 'system'} on:click={() => { themeMode = 'system'; handleThemeModeChange(); }} title="System">◑</button>
                  <button type="button" class="theme-opt" class:theme-opt-active={themeMode === 'dark'} on:click={() => { themeMode = 'dark'; handleThemeModeChange(); }} title="Dark">☽</button>
                </div>
              </div>
              <div class="popover-divider"></div>
              <button type="button" class="popover-action" on:click={triggerRefresh}>
                Refresh data
              </button>
              <div class="popover-divider"></div>
              <button type="button" class="popover-action popover-danger" on:click={handleLogout}>
                Sign out
              </button>
            </div>
          </details>
        </div>
      </header>

      <div class="content">
        <slot />
      </div>
    </section>
  </main>
{/if}

<style>
  @import './new_style.css';
</style>
