export type ThemeMode = "dark" | "light" | "auto";
export type ResolvedTheme = "dark" | "light";

export const THEME_KEY = "of.theme";

export function resolveTheme(mode: ThemeMode): ResolvedTheme {
  if (mode === "light" || mode === "dark") return mode;
  return window.matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
}

export function storedTheme(): ThemeMode | null {
  try {
    const value = window.localStorage.getItem(THEME_KEY);
    return value === "dark" || value === "light" || value === "auto" ? value : null;
  } catch {
    return null;
  }
}

export function applyTheme(mode: ThemeMode): ResolvedTheme {
  const resolved = resolveTheme(mode);
  const root = document.documentElement;
  root.dataset.theme = resolved;
  root.style.colorScheme = resolved;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", resolved === "light" ? "#f4f3ee" : "#08090b");
  return resolved;
}

export function persistTheme(mode: ThemeMode): void {
  try {
    window.localStorage.setItem(THEME_KEY, mode);
  } catch {
    /* private mode */
  }
}
