import { useEffect, useState } from "react";
import { applyTheme, followsSystemTheme, getInitialTheme, type Theme } from "./theme";

export function ThemeSwitch() {
  const [theme, setTheme] = useState<Theme>(getInitialTheme);

  useEffect(() => {
    const preference = window.matchMedia("(prefers-color-scheme: light)");
    const follow = (event: MediaQueryListEvent) => {
      if (!followsSystemTheme()) return;
      const next = event.matches ? "light" : "dark";
      document.documentElement.dataset.theme = next;
      document.documentElement.style.colorScheme = next;
      setTheme(next);
    };
    preference.addEventListener("change", follow);
    return () => preference.removeEventListener("change", follow);
  }, []);

  const choose = (next: Theme) => {
    applyTheme(next);
    setTheme(next);
  };

  return <div className="theme-switch" role="group" aria-label="Color theme">
    <span className="sr-only" aria-live="polite">{theme} theme active</span>
    <button type="button" aria-pressed={theme === "light"} onClick={() => choose("light")}>Light</button>
    <button type="button" aria-pressed={theme === "dark"} onClick={() => choose("dark")}>Dark</button>
  </div>;
}
