export type ThemeMode = 'system' | 'light' | 'dark';

const THEME_MODE_KEY = 'llmkeyrotator_theme_mode';

export function getStoredThemeMode(): ThemeMode {
  if (typeof localStorage === 'undefined') {
    return 'system';
  }

  const stored = localStorage.getItem(THEME_MODE_KEY);
  if (stored === 'light' || stored === 'dark' || stored === 'system') {
    return stored;
  }

  return 'system';
}

export function setStoredThemeMode(mode: ThemeMode) {
  if (typeof localStorage !== 'undefined') {
    localStorage.setItem(THEME_MODE_KEY, mode);
  }
}

export function resolveThemeMode(mode: ThemeMode): 'light' | 'dark' {
  if (mode === 'system') {
    if (typeof window !== 'undefined' && window.matchMedia('(prefers-color-scheme: light)').matches) {
      return 'light';
    }
    return 'dark';
  }

  return mode;
}

export function applyThemeMode(mode: ThemeMode) {
  if (typeof document === 'undefined') {
    return;
  }

  const resolved = resolveThemeMode(mode);
  document.documentElement.dataset.theme = resolved;
  document.documentElement.dataset.themeMode = mode;
  document.documentElement.style.colorScheme = resolved;
}
