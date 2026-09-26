/**
 * Типы запусков (executions) — зеркала backend-схем из
 * `app/shared/schemas/execution.py`. Единый источник для REST-клиента и
 * WS-типов (live-логи 5.B импортируют `Execution`/`ExecutionStep` отсюда).
 */

/** Статусы запуска. `queued`/`running` — активные; остальные терминальные. */
export type ExecutionStatus =
    | "queued"
    | "running"
    | "succeeded"
    | "failed"
    | "dead"
    | "canceled";

export const TERMINAL_STATUSES: readonly ExecutionStatus[] = [
    "succeeded",
    "failed",
    "dead",
    "canceled",
];

/** Активные статусы: запуск ещё идёт или ждёт в очереди (для автообновления). */
export const ACTIVE_STATUSES: readonly ExecutionStatus[] = ["queued", "running"];

export function isTerminalStatus(status: string): boolean {
    return (TERMINAL_STATUSES as readonly string[]).includes(status);
}

export function isActiveStatus(status: string): boolean {
    return (ACTIVE_STATUSES as readonly string[]).includes(status);
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

/** Детали запуска: сам запуск + все его шаги (GET /executions/{id}). */
export interface ExecutionDetail extends Execution {
    steps: ExecutionStep[];
}

/** Страница списка запусков (GET /workspaces/{ws}/executions). */
export interface ExecutionListResponse {
    items: Execution[];
    next_cursor: string | null;
}