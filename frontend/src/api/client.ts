import { useAuthStore } from "@/stores/authStore";

export class ApiError extends Error {
    status: number;
    body: unknown;

    constructor(status: number, body: unknown, message: string) {
        super(message);
        this.name = "ApiError";
        this.status = status;
        this.body = body;
    }
}

interface RequestOptions {
    method?: string;
    body?: unknown;
    signal?: AbortSignal;
}

async function parseBody(response: Response): Promise<unknown> {
    const text = await response.text();
    if (!text) return null;
    try {
        return JSON.parse(text);
    } catch {
        return text;
    }
}

function messageFrom(status: number, body: unknown): string {
    if (body && typeof body === "object" && "detail" in body) {
        const detail = (body as { detail: unknown }).detail;
        if (typeof detail === "string") return detail;
        if (detail && typeof detail === "object" && "message" in detail) {
            return String((detail as { message: unknown }).message);
        }
    }
    return `Request failed with status ${status}`;
}

let refreshInFlight: Promise<boolean> | null = null;

/** Обновление access-токена по httpOnly refresh-cookie. Один параллельный запрос на всех. */
async function refreshAccessToken(): Promise<boolean> {
    if (refreshInFlight === null) {
        refreshInFlight = (async () => {
            try {
                const response = await fetch("/api/auth/refresh", {
                    method: "POST",
                    credentials: "include",
                });
                if (!response.ok) return false;
                const data = (await response.json()) as { access_token: string };
                useAuthStore.getState().setAccessToken(data.access_token);
                return true;
            } catch {
                return false;
            } finally {
                refreshInFlight = null;
            }
        })();
    }
    return refreshInFlight;
}

async function rawRequest(path: string, options: RequestOptions): Promise<Response> {
    const { accessToken } = useAuthStore.getState();
    const headers: Record<string, string> = {};
    if (options.body !== undefined) headers["Content-Type"] = "application/json";
    if (accessToken) headers["Authorization"] = `Bearer ${accessToken}`;

    return fetch(path, {
        method: options.method ?? "GET",
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        credentials: "include",
        signal: options.signal,
    });
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
    let response = await rawRequest(path, options);

    if (response.status === 401) {
        // одна повторная попытка после refresh; если не вышло — сессия кончилась
        const refreshed = await refreshAccessToken();
        if (refreshed) {
            response = await rawRequest(path, options);
        } else {
            useAuthStore.getState().clear();
        }
    }

    if (!response.ok) {
        const body = await parseBody(response);
        throw new ApiError(response.status, body, messageFrom(response.status, body));
    }

    const body = await parseBody(response);
    return body as T;
}

/** Восстановление сессии при старте приложения: refresh-cookie → access-токен. */
export async function bootstrapSession(): Promise<boolean> {
    if (useAuthStore.getState().accessToken) return true;
    return refreshAccessToken();
}

export async function logout(): Promise<void> {
    try {
        await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    } finally {
        useAuthStore.getState().clear();
    }
}