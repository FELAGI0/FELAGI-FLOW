import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createCredential, deleteCredential, listCredentials } from "@/api/credentials";
import { useAuthStore } from "@/stores/authStore";

/**
 * Тесты API-клиента credentials: URL, метод, тело, разворачивание items.
 * fetch мокается - реальной сети нет.
 */

function jsonResponse(body: unknown, status = 200): Response {
    return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json" },
    });
}

describe("credentials API client", () => {
    let fetchMock: ReturnType<typeof vi.fn>;

    beforeEach(() => {
        fetchMock = vi.fn().mockResolvedValue(jsonResponse({ items: [] }));
        vi.stubGlobal("fetch", fetchMock);
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

    it("listCredentials: разворачивает items и строит URL", async () => {
        fetchMock.mockResolvedValueOnce(
            jsonResponse({ items: [{ id: "c1", service: "telegram", auth_type: "bot_token", name: "bot", created_at: "x" }] }),
        );
        const result = await listCredentials("ws-1");
        expect(calledUrl()).toBe("/api/workspaces/ws-1/credentials");
        expect(result).toHaveLength(1);
        expect(result[0].name).toBe("bot");
    });

    it("createCredential: POST с service/name/payload", async () => {
        fetchMock.mockResolvedValueOnce(jsonResponse({ id: "c1" }, 201));
        await createCredential("ws-1", {
            service: "telegram",
            name: "bot",
            payload: { token: "123" },
        });
        expect(calledUrl()).toBe("/api/workspaces/ws-1/credentials");
        expect(calledInit().method).toBe("POST");
        expect(JSON.parse(String(calledInit().body))).toEqual({
            service: "telegram",
            name: "bot",
            payload: { token: "123" },
        });
    });

    it("deleteCredential: DELETE на id", async () => {
        fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));
        await deleteCredential("ws-1", "c-9");
        expect(calledUrl()).toBe("/api/workspaces/ws-1/credentials/c-9");
        expect(calledInit().method).toBe("DELETE");
    });
});
