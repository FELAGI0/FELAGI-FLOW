import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { getExecution } from "@/api/executions";
import { connectExecutionLogs, isFatalCloseCode } from "@/api/ws";
import type { Execution, ExecutionStep } from "@/types/execution";

/**
 * Live-подписка на шаги запуска (5.C.2).
 *
 * Основной канал — WebSocket `/ws/executions/{id}`: snapshot заменяет
 * состояние, `steps` добавляет новые шаги (дедупликация по id), `finished`
 * фиксирует финальный статус.
 *
 * Если WS не поднимается (исчерпаны попытки переподключения) — переходим в
 * `fallback`: включаем polling через TanStack Query, чтобы UI не «замер».
 * При постоянных ошибках (невалидный токен/нет доступа) — `closed`, без реконнекта.
 */

export type ConnectionState =
    | "connecting"
    | "live"
    | "reconnecting"
    | "closed"
    | "fallback";

export interface ExecutionLogsState {
    execution: Execution | null;
    steps: ExecutionStep[];
    connectionState: ConnectionState;
    error: string | null;
}

/** Дописать новые шаги, не дублируя уже известные (по id) и сохраняя порядок. */
export function mergeSteps(
    current: ExecutionStep[],
    incoming: ExecutionStep[],
): ExecutionStep[] {
    const seen = new Set(current.map((step) => step.id));
    const additions = incoming.filter((step) => !seen.has(step.id));
    return additions.length === 0 ? current : [...current, ...additions];
}

const FALLBACK_POLL_MS = 3000;

export function useExecutionLogs(
    executionId: string,
    accessToken: string | null,
): ExecutionLogsState {
    const [execution, setExecution] = useState<Execution | null>(null);
    const [steps, setSteps] = useState<ExecutionStep[]>([]);
    const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");
    const [error, setError] = useState<string | null>(null);

    // fallback-канал: включается только когда WS исчерпал попытки
    const fallbackQuery = useQuery({
        queryKey: ["execution", executionId, "fallback"],
        queryFn: () => getExecution(executionId),
        enabled: connectionState === "fallback",
        refetchInterval: connectionState === "fallback" ? FALLBACK_POLL_MS : false,
    });

    // пока в fallback — источник истины опрос, а не WS
    useEffect(() => {
        if (connectionState === "fallback" && fallbackQuery.data) {
            setExecution(fallbackQuery.data);
            setSteps(fallbackQuery.data.steps);
        }
    }, [connectionState, fallbackQuery.data]);

    useEffect(() => {
        if (!executionId) return;
        setConnectionState("connecting");
        setError(null);

        const handle = connectExecutionLogs(
            executionId,
            {
                onOpen: () => setConnectionState("live"),
                onSnapshot: (message) => {
                    setExecution(message.execution);
                    setSteps(message.steps);
                    setConnectionState("live");
                },
                onSteps: (message) => setSteps((current) => mergeSteps(current, message.steps)),
                onFinished: (message) => {
                    setExecution((current) =>
                        current
                            ? { ...current, status: message.status, error: message.error }
                            : current,
                    );
                    setConnectionState("closed");
                },
                onReconnecting: () => setConnectionState("reconnecting"),
                onExhausted: () => setConnectionState("fallback"),
                onClose: (code) => {
                    // 1000 — нормальное завершение; «фатальные» коды — реконнект не поможет
                    if (code === 1000 || isFatalCloseCode(code)) {
                        setConnectionState("closed");
                    }
                },
                onError: (message) => {
                    setError(message);
                    // нет токена и т.п.: соединение не открылось — из «connecting» в «closed»
                    setConnectionState((prev) => (prev === "connecting" ? "closed" : prev));
                },
            },
            { token: accessToken ?? undefined },
        );

        return () => handle.close();
    }, [executionId, accessToken]);

    return { execution, steps, connectionState, error };
}