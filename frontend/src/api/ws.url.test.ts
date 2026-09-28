/**
 * URL WebSocket live-логов: схема и хост выводятся из окружения (Deploy.1).
 *
 * Без VITE_API_URL (как в тестах) база — origin страницы (jsdom: localhost),
 * и сокет идёт на ws://. Проверяем форму URL и что токен уходит в query.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { connectExecutionLogs } from "@/api/ws";
import { MockWebSocket } from "@/test-utils/mockWebSocket";

describe("ws URL", () => {
    let restore: () => void;

    beforeEach(() => {
        restore = MockWebSocket.install();
    });

    afterEach(() => {
        restore();
    });

    it("по умолчанию — ws:// на origin страницы, токен в query", () => {
        const handle = connectExecutionLogs("exec-1", {}, { token: "tok-123" });
        const url = new URL(MockWebSocket.last().url);

        expect(url.protocol).toBe("ws:");
        expect(url.host).toBe(window.location.host);
        expect(url.pathname).toBe("/ws/executions/exec-1");
        expect(url.searchParams.get("token")).toBe("tok-123");

        handle.close();
    });

    it("с VITE_API_URL (https) — wss:// на хосте api", async () => {
        // API_BASE вычисляется на импорте модуля → пере-импортируем с env
        vi.stubEnv("VITE_API_URL", "https://felagi-api.onrender.com");
        vi.resetModules();
        const { connectExecutionLogs: connect } = await import("@/api/ws");

        const handle = connect("exec-2", {}, { token: "tok-9" });
        const url = new URL(MockWebSocket.last().url);

        expect(url.protocol).toBe("wss:");
        expect(url.host).toBe("felagi-api.onrender.com");
        expect(url.pathname).toBe("/ws/executions/exec-2");
        expect(url.searchParams.get("token")).toBe("tok-9");

        handle.close();
        vi.unstubAllEnvs();
    });
});