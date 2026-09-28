import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useTheme } from "@/hooks/useTheme";
import { useThemeStore } from "@/stores/themeStore";
import { flush, renderHook } from "@/test-utils/renderHook";

/**
 * Заглушка matchMedia: запоминает текущее значение prefers-color-scheme
 * и позволяет дёрнуть 'change'.
 */
function installMatchMedia(initial: boolean): { matches: () => boolean; change: (value: boolean) => void } {
    const state = { matches: initial };
    const listeners = new Set<(event: { matches: boolean }) => void>();

    vi.stubGlobal("matchMedia", vi.fn().mockImplementation((query: string) => {
        if (query !== "(prefers-color-scheme: dark)") {
            throw new Error(`unexpected media query: ${query}`);
        }
        return {
            get matches() {
                return state.matches;
            },
            addEventListener: (_: string, listener: (event: { matches: boolean }) => void) => {
                listeners.add(listener);
            },
            removeEventListener: (_: string, listener: (event: { matches: boolean }) => void) => {
                listeners.delete(listener);
            },
        };
    }));

    return {
        matches: () => state.matches,
        change: (value: boolean) => {
            state.matches = value;
            for (const listener of listeners) listener({ matches: value });
        },
    };
}

beforeEach(() => {
    window.localStorage.clear();
    useThemeStore.setState({ theme: "system" });
    document.documentElement.className = "";
});

afterEach(() => {
    vi.unstubAllGlobals();
});

describe("useTheme", () => {
    it("'dark' -> класс dark на documentElement", async () => {
        act(() => useThemeStore.getState().setTheme("dark"));
        renderHook(() => useTheme());
        await flush();

        expect(document.documentElement.classList.contains("dark")).toBe(true);
    });

    it("'light' -> класс dark отсутствует", async () => {
        act(() => useThemeStore.getState().setTheme("light"));
        renderHook(() => useTheme());
        await flush();

        expect(document.documentElement.classList.contains("dark")).toBe(false);
    });

    it("'system' + matchMedia(true) -> класс dark", async () => {
        installMatchMedia(true);
        renderHook(() => useTheme());
        await flush();

        expect(document.documentElement.classList.contains("dark")).toBe(true);
    });

    it("'system' + matchMedia(false) -> класс dark отсутствует", async () => {
        installMatchMedia(false);
        renderHook(() => useTheme());
        await flush();

        expect(document.documentElement.classList.contains("dark")).toBe(false);
    });

    it("'system': смена prefers-color-scheme обновляет класс", async () => {
        const media = installMatchMedia(false);
        renderHook(() => useTheme());
        await flush();
        expect(document.documentElement.classList.contains("dark")).toBe(false);

        media.change(true);
        expect(document.documentElement.classList.contains("dark")).toBe(true);

        media.change(false);
        expect(document.documentElement.classList.contains("dark")).toBe(false);
    });

    it("matchMedia отсутствует (jsdom) -> хук не падает, класс dark снят", async () => {
        // в jsdom window.matchMedia не реализован; на всякий случай удаляем
        vi.stubGlobal("matchMedia", undefined);
        renderHook(() => useTheme());
        await flush();

        expect(document.documentElement.classList.contains("dark")).toBe(false);
    });
});