import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useExecutionLogs } from "@/hooks/useExecutionLogs";
import { MockWebSocket } from "@/test-utils/mockWebSocket";
import { flush, renderHook } from "@/test-utils/renderHook";
import type { Execution, ExecutionStep } from "@/types/execution";

const EXECUTION: Execution = {
    id: "exec-1",
    workflow_id: "wf-1",
    workflow_version_id: "ver-1",
    status: "running",
    trigger_type: "manual",
    trigger_payload: {},
    attempts: 1,
    max_attempts: 3,
    error: null,
    created_at: "2026-09-26T12:00:00Z",
    started_at: "2026-09-26T12:00:01Z",
    finished_at: null,
};

function step(id: string, nodeId = id): ExecutionStep {
    return {
        id,
        node_id: nodeId,
        node_type: "debug",
        attempt: 1,
        status: "succeeded",
        input: null,
        output: null,
        error: null,
        warnings: [],
        duration_ms: 1,
    };
}

/** Подключить хук, «открыть» сокет и отдать снапшот — базовое состояние. */
async function mountLive() {
    const rendered = renderHook(() => useExecutionLogs("exec-1", "test-token"));
    const socket = MockWebSocket.last();
    await act(async () => {
        socket.simulateOpen();
    });
    return { rendered, socket };
}

describe("useExecutionLogs", () => {
    let restore: () => void;

    beforeEach(() => {
        restore = MockWebSocket.install();
        // fallback использует fetch: заглушаем, чтобы не улететь в сеть
        vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    });

    afterEach(() => {
        restore();
        vi.unstubAllGlobals();
        vi.useRealTimers();
    });

    it("подключается: connecting → live, ставит execution и steps из snapshot", async () => {
        const { rendered, socket } = await mountLive();

        // до snapshot (сразу после open) — live
        expect(rendered.result.current.connectionState).toBe("live");

        await act(async () => {
            socket.simulateMessage({
                type: "snapshot",
                execution: EXECUTION,
                steps: [step("s1"), step("s2")],
            });
        });

        expect(rendered.result.current.execution?.id).toBe("exec-1");
        expect(rendered.result.current.steps.map((s) => s.id)).toEqual(["s1", "s2"]);
        rendered.unmount();
    });

    it("initial state — connecting, пока сокет не открылся", async () => {
        const rendered = renderHook(() => useExecutionLogs("exec-1", "test-token"));
        expect(rendered.result.current.connectionState).toBe("connecting");
        expect(rendered.result.current.execution).toBeNull();
        rendered.unmount();
    });

    it("новый step добавляется в конец", async () => {
        const { rendered, socket } = await mountLive();
        await act(async () => {
            socket.simulateMessage({ type: "snapshot", execution: EXECUTION, steps: [step("s1")] });
        });
        await act(async () => {
            socket.simulateMessage({ type: "steps", steps: [step("s2")] });
        });
        expect(rendered.result.current.steps.map((s) => s.id)).toEqual(["s1", "s2"]);
        rendered.unmount();
    });

    it("дубликат step (тот же id) не добавляется дважды", async () => {
        const { rendered, socket } = await mountLive();
        await act(async () => {
            socket.simulateMessage({ type: "snapshot", execution: EXECUTION, steps: [step("s1")] });
        });
        await act(async () => {
            socket.simulateMessage({ type: "steps", steps: [step("s1"), step("s2")] });
        });
        expect(rendered.result.current.steps.map((s) => s.id)).toEqual(["s1", "s2"]);
        rendered.unmount();
    });

    it("finished обновляет статус и переводит в closed", async () => {
        const { rendered, socket } = await mountLive();
        await act(async () => {
            socket.simulateMessage({ type: "snapshot", execution: EXECUTION, steps: [] });
        });
        await act(async () => {
            socket.simulateMessage({ type: "finished", status: "succeeded", error: null });
        });
        expect(rendered.result.current.execution?.status).toBe("succeeded");
        expect(rendered.result.current.connectionState).toBe("closed");
        rendered.unmount();
    });

    it("close 4401 → closed, без реконнекта", async () => {
        const { rendered, socket } = await mountLive();
        await act(async () => {
            socket.simulateClose(4401);
        });
        expect(rendered.result.current.connectionState).toBe("closed");
        expect(rendered.result.current.error).toContain("4401");
        // реконнекта нет: новых сокетов не появилось
        expect(MockWebSocket.instances).toHaveLength(1);
        rendered.unmount();
    });

    it("close 4404 → closed, без реконнекта", async () => {
        const { rendered, socket } = await mountLive();
        await act(async () => {
            socket.simulateClose(4404);
        });
        expect(rendered.result.current.connectionState).toBe("closed");
        expect(MockWebSocket.instances).toHaveLength(1);
        rendered.unmount();
    });

    it("close 4429 (лимит соединений) → closed, без реконнекта", async () => {
        const { rendered, socket } = await mountLive();
        await act(async () => {
            socket.simulateClose(4429);
        });
        expect(rendered.result.current.connectionState).toBe("closed");
        expect(MockWebSocket.instances).toHaveLength(1);
        rendered.unmount();
    });

    it("сетевой разрыв → 3 попытки, затем fallback", async () => {
        vi.useFakeTimers();
        const rendered = renderHook(() => useExecutionLogs("exec-1", "test-token"));

        // сеть недоступна: соединение создаётся, но НЕ открывается и аномально
        // закрывается (1006). Успешный open сбрасывал бы backoff — тогда
        // исчерпания не случилось бы, поэтому здесь open не эмулируем.
        for (let attempt = 0; attempt < 3; attempt += 1) {
            await act(async () => {
                MockWebSocket.last().simulateClose(1006);
            });
            expect(rendered.result.current.connectionState).toBe("reconnecting");
            // ждём backoff: запланированный open() создаст следующий сокет
            await act(async () => {
                vi.advanceTimersByTime(30_000);
            });
        }

        // 4-й сокет закрывается — попытки исчерпаны
        await act(async () => {
            MockWebSocket.last().simulateClose(1006);
        });

        expect(rendered.result.current.connectionState).toBe("fallback");
        // исходное + 3 реконнекта = 4 сокета
        expect(MockWebSocket.instances.length).toBe(4);
        rendered.unmount();
    });

    it("успешный реконнект сбрасывает backoff и снова даёт live", async () => {
        vi.useFakeTimers();
        const rendered = renderHook(() => useExecutionLogs("exec-1", "test-token"));

        await act(async () => {
            MockWebSocket.last().simulateOpen();
            MockWebSocket.last().simulateClose(1006);
        });
        expect(rendered.result.current.connectionState).toBe("reconnecting");

        await act(async () => {
            vi.advanceTimersByTime(2000);
        });
        // реконнект поднялся и открылся успешно
        await act(async () => {
            MockWebSocket.last().simulateOpen();
        });
        expect(rendered.result.current.connectionState).toBe("live");
        rendered.unmount();
    });

    it("нет токена → connecting переходит в closed с ошибкой", async () => {
        const rendered = renderHook(() => useExecutionLogs("exec-1", null));
        await flush();
        expect(rendered.result.current.connectionState).toBe("closed");
        expect(rendered.result.current.error).toContain("токен");
        rendered.unmount();
    });

    it("unmount закрывает сокет", async () => {
        const { rendered, socket } = await mountLive();
        rendered.unmount();
        expect(socket.readyState).toBe(MockWebSocket.CLOSED);
    });
});