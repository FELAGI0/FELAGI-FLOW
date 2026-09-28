import { create } from "zustand";
import { persist } from "zustand/middleware";

/**
 * Тема UI.1. Хранится в localStorage (persist), применяется хуком useTheme.
 *
 * 'system' — следовать prefers-color-scheme; сам слушатель media-query живёт
 * в useTheme (стор остаётся чистым состоянием без побочных эффектов DOM).
 */
export type Theme = "light" | "dark" | "system";

/** Порядок цикла для кнопки-переключателя в шапке. */
export const THEME_CYCLE: readonly Theme[] = ["light", "dark", "system"] as const;

export function nextTheme(theme: Theme): Theme {
    const index = THEME_CYCLE.indexOf(theme);
    return THEME_CYCLE[(index + 1) % THEME_CYCLE.length];
}

export interface ThemeState {
    theme: Theme;
    setTheme: (theme: Theme) => void;
}

export const useThemeStore = create<ThemeState>()(
    persist(
        (set) => ({
            theme: "system",
            setTheme: (theme) => set({ theme }),
        }),
        { name: "felagi-theme" },
    ),
);