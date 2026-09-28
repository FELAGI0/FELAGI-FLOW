import { beforeEach, describe, expect, it } from "vitest";

import { nextTheme, useThemeStore } from "@/stores/themeStore";

const STORAGE_KEY = "felagi-theme";

beforeEach(() => {
    window.localStorage.clear();
    useThemeStore.setState({ theme: "system" });
});

describe("themeStore", () => {
    it("default = system", () => {
        expect(useThemeStore.getState().theme).toBe("system");
    });

    it("setTheme меняет theme", () => {
        useThemeStore.getState().setTheme("dark");
        expect(useThemeStore.getState().theme).toBe("dark");

        useThemeStore.getState().setTheme("light");
        expect(useThemeStore.getState().theme).toBe("light");
    });

    it("persist сохраняет theme в localStorage", () => {
        useThemeStore.getState().setTheme("dark");

        const raw = window.localStorage.getItem(STORAGE_KEY);
        expect(raw).not.toBeNull();
        expect(JSON.parse(raw as string)).toEqual({ state: { theme: "dark" }, version: 0 });
    });

    it("nextTheme: light -> dark -> system -> light", () => {
        expect(nextTheme("light")).toBe("dark");
        expect(nextTheme("dark")).toBe("system");
        expect(nextTheme("system")).toBe("light");
    });
});