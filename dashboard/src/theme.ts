export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "token-by-token-theme";

const validTheme = (value: string | null): value is Theme => value === "light" || value === "dark";

export function getInitialTheme(): Theme {
  const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
  if (validTheme(stored)) return stored;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
  window.localStorage.setItem(THEME_STORAGE_KEY, theme);
}

export function followsSystemTheme(): boolean {
  return !validTheme(window.localStorage.getItem(THEME_STORAGE_KEY));
}
