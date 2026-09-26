/**
 * Типы сообщений WebSocket live-логов execution (этап 5.B).
 *
 * Зеркалят серверные ответы `WS /ws/executions/{id}`. Источник истины — БД:
 * NOTIFY несёт только id запуска, а сами шаги приходят в messages `snapshot`
 * и `steps`.
 */

/** Статусы запуска, при которых live-подписка закрывается (сервер → close 1000). */
export type ExecutionStatus = "queued" | "running" | "succeeded" | "failed" | "dead" | "canceled";

export const TERMINAL_STATUSES: readonly ExecutionStatus[] = [
    "succeeded",
    "failed",
    "dead",
    "canceled",
];

export function isTerminalStatus(status: ExecutionStatus): boolean {
    return TERMINAL_STATUSES.includes(status);
}

/** Шаг выполнения — совпадает с backend ExecutionStepResponse. */
export interface ExecutionStep {
    id: string;
    node_id: string;
    node_type: string;
    /** номер попытки узла при per-node retry (4.C): 1, 2, 3… */
    attempt: number;
    /** 'running' | 'succeeded' | 'failed' | 'skipped' */
    status: string;
    input: Record<string, unknown> | null;
    output: Record<string, unknown> | null;
    error: string | null;
    warnings: string[];
    duration_ms: number | null;
}

/** Запуск — совпадает с backend ExecutionResponse. */
export interface Execution {
    id: string;
    workflow_id: string;
    workflow_version_id: string;
    status: ExecutionStatus;
    trigger_type: string;
    trigger_payload: Record<string, unknown> | null;
    attempts: number;
    max_attempts: number;
    error: string | null;
    created_at: string;
    started_at: string | null;
    finished_at: string | null;
}

/** Первое сообщение при подключении: текущее состояние запуска и все его шаги. */
export interface SnapshotMessage {
    type: "snapshot";
    execution: Execution;
    steps: ExecutionStep[];
}

/** Новые шаги, появившиеся после снапшота (идемпотентно: клиент дедуплицирует по id). */
export interface StepsMessage {
    type: "steps";
    steps: ExecutionStep[];
}

/** Терминальный статус: после него сервер закрывает соединение (code 1000). */
export interface FinishedMessage {
    type: "finished";
    status: ExecutionStatus;
    error: string | null;
}

/** keep-alive против idle-таймаутов прокси; клиент может игнорировать. */
export interface PingMessage {
    type: "ping";
}

export type ServerMessage =
    | SnapshotMessage
    | StepsMessage
    | FinishedMessage
    | PingMessage;