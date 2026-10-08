import { useEffect } from "react";

import { type Theme, useThemeStore } from "@/stores/themeStore";

/**
 * Применяет выбранную тему к документу (UI.1): вешает/снимает класс 'dark'
 * на <html>. Для 'light'/'dark' - по значению стора; для 'system' - слушает
 * matchMedia('(prefers-color-scheme: dark)') и реагирует на смену схемы ОС.
 *
 * Хук вызывается из Layout - один раз на приложение.
 */
export function useTheme(): Theme {
    const theme = useThemeStore((state) => state.theme);

    useEffect(() => {
        const root = document.documentElement;

        function apply(prefersDark: boolean) {
            const dark = theme === "dark" || (theme === "system" && prefersDark);
            root.classList.toggle("dark", dark);
        }

        if (theme !== "system") {
            apply(false);
            return;
        }

        // matchMedia есть не во всех средах (jsdom) - деградируем к светлой
        if (typeof window.matchMedia !== "function") {
            apply(false);
            return;
        }

        const media = window.matchMedia("(prefers-color-scheme: dark)");
        apply(media.matches);
        const onChange = (event: MediaQueryListEvent) => apply(event.matches);
        media.addEventListener("change", onChange);
        return () => media.removeEventListener("change", onChange);
    }, [theme]);

    return theme;
}
