import { useSyncExternalStore } from 'react';

export type Theme = 'general' | 'light' | 'black';

const storageKey = 'low-prior-theme';
const listeners = new Set<() => void>();
const themeColors: Record<Theme, string> = { general: '#07111f', light: '#edf2f6', black: '#060606' };
let currentTheme: Theme = 'general';
let initialized = false;

function isTheme(value: unknown): value is Theme {
  return value === 'general' || value === 'light' || value === 'black';
}

function applyTheme(theme: Theme) {
  currentTheme = theme;
  document.documentElement.dataset.theme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', themeColors[theme]);
  listeners.forEach(listener => listener());
}

/** Call before rendering so every subscriber shares one appearance preference. */
export function initializeTheme() {
  if (initialized || typeof window === 'undefined') return;
  initialized = true;
  let saved: string | null = null;
  try { saved = window.localStorage.getItem(storageKey); } catch { /* Storage may be disabled. */ }
  applyTheme(isTheme(saved) ? saved : 'general');
  window.addEventListener('storage', event => {
    if (event.key === storageKey || event.key === null) {
      applyTheme(isTheme(event.newValue) ? event.newValue : 'general');
    }
  });
}

function setTheme(theme: Theme) {
  applyTheme(theme);
  try { window.localStorage.setItem(storageKey, theme); } catch { /* Keep the preference for this session. */ }
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}

export function useTheme() {
  const theme = useSyncExternalStore(subscribe, () => currentTheme, (): Theme => 'general');
  return { theme, setTheme };
}
