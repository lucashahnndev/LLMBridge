<script lang="ts">
  import { onMount } from 'svelte';
  import { goto } from '$app/navigation';
  import { page } from '$app/stores';
  import { clearStoredAdminToken, getStoredAdminToken, logoutAdmin } from '$lib/api';
  import { applyThemeMode, getStoredThemeMode, setStoredThemeMode, type ThemeMode } from '$lib/theme';
  import { activeSection, topbarTitle, refreshTrigger, type SectionKey } from '$lib/stores';
  import {
    LayoutDashboard,
    Key,
    Coins,
    Layers3,
    Activity,
    Settings,
    PanelLeftClose,
    PanelLeftOpen,
    BookOpenText,
    SquareTerminal
  } from 'lucide-svelte';

  let token = '';
  let themeMode: ThemeMode = 'system';
  let isMounted = false;
  let hideBrandWordmark = false;
  let sidebarPinnedOpen = false;
  let sidebarHovered = false;
  let sidebarHoverLocked = false;

  const sections: Array<{ key: SectionKey; label: string; icon: typeof LayoutDashboard }> = [
    { key: 'overview', label: 'Overview', icon: LayoutDashboard },
    { key: 'keys', label: 'Provider Keys', icon: Key },
    { key: 'tokens', label: 'App Tokens', icon: Coins },
    { key: 'queues', label: 'Model Queues', icon: Layers3 },
    { key: 'usage', label: 'Usage', icon: Activity },
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

  function handleSidebarToggle() {
    if (sidebarPinnedOpen) {
      sidebarPinnedOpen = false;
      sidebarHovered = false;
      sidebarHoverLocked = true;
      return;
    }

    sidebarPinnedOpen = true;
    sidebarHovered = true;
    sidebarHoverLocked = false;
  }

  function handleSidebarMouseEnter() {
    if (!sidebarPinnedOpen && !sidebarHoverLocked) {
      sidebarHovered = true;
    }
  }

  function handleSidebarMouseLeave() {
    sidebarHovered = false;
    sidebarHoverLocked = false;
  }

  $: hideBrandWordmark = $page.url.pathname.startsWith('/app/playground');

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
  <main
    class="shell"
    class:sidebar-collapsed={!sidebarPinnedOpen && !sidebarHovered}
    class:sidebar-hover-preview={sidebarHovered && !sidebarPinnedOpen}
    class:sidebar-pinned-open={sidebarPinnedOpen}
  >
    <aside
      class="sidebar"
      on:mouseenter={handleSidebarMouseEnter}
      on:mouseleave={handleSidebarMouseLeave}
    >
      <div class="sidebar-panel">
        <div class="brand">
          {#if !sidebarPinnedOpen && !sidebarHovered}
            <div class="brand-icon">LB</div>
          {:else}
            {#if !hideBrandWordmark}
              <div class="eyebrow">LLMBridge</div>
            {/if}
            <h1>Control plane</h1>
          {/if}
        </div>

        <nav class="nav">
          {#each sections as section}
            <button
              type="button"
              class:active={$page.url.pathname === '/app' && $activeSection === section.key}
              on:click={() => handleNavClick(section.key)}
              title={!sidebarPinnedOpen && !sidebarHovered ? section.label : ''}
            >
              <span class="nav-icon"><svelte:component this={section.icon} size={15} strokeWidth={1.6} /></span>
              {#if sidebarPinnedOpen || sidebarHovered}
                <span class="nav-label">{section.label}</span>
              {/if}
            </button>
          {/each}
          <button
            type="button"
            class:active={$page.url.pathname === '/app/playground'}
            on:click={() => goto('/app/playground')}
            title={!sidebarPinnedOpen && !sidebarHovered ? 'Playground' : ''}
          >
            <span class="nav-icon"><SquareTerminal size={15} strokeWidth={1.6} /></span>
            {#if sidebarPinnedOpen || sidebarHovered}
              <span class="nav-label">Playground</span>
            {/if}
          </button>
        </nav>

        <div class="sidebar-footer">
          <button
            class="collapse-btn"
            on:click={handleSidebarToggle}
            title={sidebarPinnedOpen ? 'Unpin sidebar' : 'Pin sidebar open'}
            aria-pressed={sidebarPinnedOpen}
            aria-expanded={sidebarPinnedOpen || sidebarHovered}
          >
            <span class="nav-icon">
              {#if sidebarPinnedOpen}
                <PanelLeftClose size={15} strokeWidth={1.6} />
              {:else}
                <PanelLeftOpen size={15} strokeWidth={1.6} />
              {/if}
            </span>
            {#if sidebarPinnedOpen || sidebarHovered}
              <span class="nav-label">{sidebarPinnedOpen ? 'Unpin' : 'Pin open'}</span>
            {/if}
          </button>
        </div>
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
