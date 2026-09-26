import { useAuthStore } from "@/stores/authStore";
import type { ServerMessage } from "@/types/ws";

/**
 * Обёртка над WebSocket live-логов execution (этап 5.B).
 *
 * Особенности:
 * - токен передаётся в query (`?token=…`): браузерный WebSocket не умеет
 *   кастомные заголовки, поэтому access-токен идёт параметром URL;
 * - при разрыве — переподключение с экспоненциальной задержкой
 *   (1s, 2s, 4s …, максимум 30s);
 * - после каждого переподключения сервер снова присылает `snapshot` со всеми
 *   шагами, поэтому клиент не обязан помнить состояние — он просто заменяет его.
 */

const INITIAL_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30_000;

/** Близкие коды закрытия, при которых переподключаться бессмысленно. */
const NO_RECONNECT_CODES = new Set([
    4401, // невалидный токен
    4404, // нет доступа/запуска
    4429, // превышен лимит соединений
]);

export interface ExecutionLogsCallbacks {
    /** Снапшот: полное состояние (перезаписывает накопленное у клиента). */
    onSnapshot?: (message: Extract<ServerMessage, { type: "snapshot" }>) => void;
    /** Дельты: шаги, которых у клиента ещё нет. */
    onSteps?: (message: Extract<ServerMessage, { type: "steps" }>) => void;
    /** Запуск завершился; соединение будет закрыто сервером с кодом 1000. */
    onFinished?: (message: Extract<ServerMessage, { type: "finished" }>) => void;
    /** Ошибка соединения или прикладное закрытие; аргумент — причина. */
    onError?: (error: string) => void;
}

export interface ExecutionLogsHandle {
    close: () => void;
}

function wsUrl(executionId: string, token: string): string {
    const scheme = window.location.protocol === "https:" ? "wss" : "ws";
    const params = new URLSearchParams({ token });
    return `${scheme}://${window.location.host}/ws/executions/${executionId}?${params}`;
}

export function connectExecutionLogs(
    executionId: string,
    callbacks: ExecutionLogsCallbacks,
): ExecutionLogsHandle {
    let socket: WebSocket | null = null;
    let closed = false;
    let attempt = 0;
    let timer: ReturnType<typeof setTimeout> | null = null;

    function scheduleReconnect(): void {
        const delay = Math.min(INITIAL_BACKOFF_MS * 2 ** attempt, MAX_BACKOFF_MS);
        attempt += 1;
        timer = setTimeout(open, delay);
    }

    function open(): void {
        if (closed) return;
        const token = useAuthStore.getState().accessToken;
        if (!token) {
            callbacks.onError?.("Нет access-токена для подключения к live-логам");
            return;
        }

        socket = new WebSocket(wsUrl(executionId, token));

        socket.onopen = () => {
            // успешное подключение сбрасывает backoff
            attempt = 0;
        };

        socket.onmessage = (event: MessageEvent<string>) => {
            let message: ServerMessage;
            try {
                message = JSON.parse(event.data) as ServerMessage;
            } catch {
                callbacks.onError?.("Некорректное сообщение от сервера");
                return;
            }
            switch (message.type) {
                case "snapshot":
                    callbacks.onSnapshot?.(message);
                    break;
                case "steps":
                    callbacks.onSteps?.(message);
                    break;
                case "finished":
                    callbacks.onFinished?.(message);
                    break;
                case "ping":
                    // keep-alive: отвечать не обязательно
                    break;
            }
        };

        socket.onclose = (event: CloseEvent) => {
            socket = null;
            if (closed) return;
            if (NO_RECONNECT_CODES.has(event.code)) {
                callbacks.onError?.(`Соединение закрыто (код ${event.code})`);
                return;
            }
            // 1000 — сервер завершил подписку (finished); переподключаться не нужно
            if (event.code === 1000) return;
            scheduleReconnect();
        };

        socket.onerror = () => {
            // деталей в onerror нет — сообщим на onclose, который придёт следом
        };
    }

    open();

    return {
        close: () => {
            closed = true;
            if (timer !== null) clearTimeout(timer);
            socket?.close(1000);
            socket = null;
        },
    };
}