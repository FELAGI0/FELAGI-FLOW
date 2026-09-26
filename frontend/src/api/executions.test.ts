import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
    cancelExecution,
    getExecution,
    listExecutions,
    runWorkflow,
} from "@/api/executions";
import { useAuthStore } from "@/stores/authStore";

/**
 * Тесты API-клиента executions: проверяем URL, метод и query-параметры.
 * fetch мокается — реальной сети нет.
 */

function jsonResponse(body: unknown): Response {
    return new Response(JSON.stringify(body), {
        status: 200,
        headers: { "Content-Type": "application/json" },
    });
}

describe("executions API client", () => {
    let fetchMock: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [], next_cursor: null }));
        vi.stubGlobal("fetch", fetchMock);
        // токен, чтобы client добавил Authorization (не влияет, но приближено к реалу)
        useAuthStore.getState().setAccessToken("test-token");
    });

    afterEach(() => {
        vi.unstubAllGlobals();
        useAuthStore.getState().clear();
    });

    function calledUrl(): string {
        return fetchMock.mock.calls[0]?.[0] as string;
    }

    function calledInit(): RequestInit {
        return fetchMock.mock.calls[0]?.[1] as RequestInit;
    }

    it("listExecutions: базовый URL без параметров", async () => {
        await listExecutions("ws-1");
        expect(calledUrl()).toBe("/api/workspaces/ws-1/executions");
    });

    it("listExecutions: все параметры попадают в query", async () => {
        await listExecutions("ws-1", {
            workflow_id: "wf-1",
            status: "failed",
            limit: 50,
            cursor: "abc",
        });
        const url = calledUrl();
        expect(url).toContain("workflow_id=wf-1");
        expect(url).toContain("status=failed");
        expect(url).toContain("limit=50");
        expect(url).toContain("cursor=abc");
    });

    it("listExecutions: пустые фильтры не шлём", async () => {
        await listExecutions("ws-1", { workflow_id: undefined, status: undefined });
        expect(calledUrl()).toBe("/api/workspaces/ws-1/executions");
    });

    it("listExecutions: limit=0 всё же шлём (это явное значение)", async () => {
        await listExecutions("ws-1", { limit: 0 });
        expect(calledUrl()).toContain("limit=0");
    });

    it("getExecution: GET на детали запуска", async () => {
        await getExecution("exec-1");
        expect(calledUrl()).toBe("/api/executions/exec-1");
        expect(calledInit().method).toBe("GET");
    });

    it("runWorkflow: POST с payload", async () => {
        await runWorkflow("wf-1", { name: "Alice" });
        expect(calledUrl()).toBe("/api/workflows/wf-1/run");
        expect(calledInit().method).toBe("POST");
        expect(JSON.parse(calledInit().body as string)).toEqual({
            payload: { name: "Alice" },
        });
    });

    it("runWorkflow: без payload шлём пустой объект", async () => {
        await runWorkflow("wf-1");
        expect(JSON.parse(calledInit().body as string)).toEqual({ payload: {} });
    });

    it("cancelExecution: POST на /cancel", async () => {
        await cancelExecution("exec-1");
        expect(calledUrl()).toBe("/api/executions/exec-1/cancel");
        expect(calledInit().method).toBe("POST");
    });
});