import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { cancelExecution, getExecution } from "@/api/executions";
import { listWorkflows } from "@/api/workflows";
import { JsonViewer } from "@/components/JsonViewer";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { formatDuration, formatRelative, shortId } from "@/lib/time";
import type { ExecutionStep } from "@/types/execution";
import { isTerminalStatus } from "@/types/execution";

function MetaItem({ label, children }: { label: string; children: ReactNode }) {
    return (
        <div className="flex flex-col gap-0.5">
            <span className="text-xs text-muted-foreground">{label}</span>
            <span className="text-sm">{children}</span>
        </div>
    );
}

function StepRow({ step }: { step: ExecutionStep }) {
    const [open, setOpen] = useState(false);
    return (
        <>
            <tr
                className="cursor-pointer border-b last:border-0 hover:bg-muted/40"
                onClick={() => setOpen((current) => !current)}
                data-testid={`step-row-${step.id}`}
            >
                <td className="px-3 py-2 text-xs text-muted-foreground">
                    {open ? "▾" : "▸"}
                </td>
                <td className="px-3 py-2 font-mono text-xs">{step.node_id}</td>
                <td className="px-3 py-2 text-xs">{step.node_type}</td>
                <td className="px-3 py-2">
                    <StatusBadge status={step.status} />
                </td>
                <td className="px-3 py-2 text-xs text-muted-foreground">{step.attempt}</td>
                <td className="px-3 py-2 text-xs text-muted-foreground">
                    {step.duration_ms === null ? "—" : `${step.duration_ms}ms`}
                </td>
            </tr>
            {open && (
                <tr className="border-b bg-muted/20 last:border-0">
                    <td />
                    <td colSpan={5} className="px-3 py-3">
                        <div className="flex flex-col gap-2">
                            {step.error && (
                                <p className="rounded-md border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-900">
                                    {step.error}
                                </p>
                            )}
                            {step.warnings.length > 0 && (
                                <ul className="flex flex-col gap-1">
                                    {step.warnings.map((warning, index) => (
                                        <li
                                            key={index}
                                            className="rounded-md border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs text-amber-900"
                                        >
                                            {warning}
                                        </li>
                                    ))}
                                </ul>
                            )}
                            <JsonViewer
                                label="input"
                                value={step.input}
                                testId={`step-input-${step.id}`}
                            />
                            <JsonViewer
                                label="output"
                                value={step.output}
                                testId={`step-output-${step.id}`}
                            />
                        </div>
                    </td>
                </tr>
            )}
        </>
    );
}

export function ExecutionDetailPage() {
    const { wsId = "", executionId = "" } = useParams();
    const queryClient = useQueryClient();
    const toast = useToast();

    const executionQuery = useQuery({
        queryKey: ["execution", executionId],
        queryFn: () => getExecution(executionId),
        refetchInterval: (query) => {
            const status = query.state.data?.status;
            return status && !isTerminalStatus(status) ? 3000 : false;
        },
    });

    const workflowsQuery = useQuery({
        queryKey: ["workflows", wsId],
        queryFn: () => listWorkflows(wsId),
    });

    const cancelMutation = useMutation({
        mutationFn: () => cancelExecution(executionId),
        onSuccess: async () => {
            toast.show("Запуск отменён", "success");
            await queryClient.invalidateQueries({ queryKey: ["execution", executionId] });
        },
        onError: (error) =>
            toast.show(error instanceof Error ? error.message : "Не удалось отменить", "error"),
    });

    const execution = executionQuery.data;

    if (executionQuery.isLoading) {
        return <p className="p-8 text-sm text-muted-foreground">Загрузка…</p>;
    }
    if (!execution) {
        return <p className="p-8 text-sm text-muted-foreground">Запуск не найден.</p>;
    }

    const workflowName =
        workflowsQuery.data?.find((workflow) => workflow.id === execution.workflow_id)?.name ??
        shortId(execution.workflow_id);
    const duration = formatDuration(execution.started_at, execution.finished_at);
    const canCancel = !isTerminalStatus(execution.status);
    // Replay появится в 7.C; пока кнопка ведёт на заглушку
    const canReplay = execution.status === "failed" || execution.status === "dead";
    const hasPayload =
        execution.trigger_payload !== null && Object.keys(execution.trigger_payload).length > 0;

    return (
        <div className="mx-auto max-w-5xl p-8">
            <div className="mb-6">
                <Link
                    to={`/workspaces/${wsId}/executions`}
                    className="text-sm text-muted-foreground hover:underline"
                >
                    ← Запуски
                </Link>
                <div className="mt-1 flex items-center gap-3">
                    <h1 className="font-mono text-xl font-semibold">
                        Execution {shortId(execution.id)}
                    </h1>
                    <StatusBadge status={execution.status} />
                </div>
            </div>

            <div className="mb-6 grid grid-cols-2 gap-4 rounded-md border bg-card p-4 sm:grid-cols-3">
                <MetaItem label="Workflow">
                    <Link
                        to={`/workspaces/${wsId}/workflows/${execution.workflow_id}/edit`}
                        className="text-primary hover:underline"
                    >
                        {workflowName}
                    </Link>
                </MetaItem>
                <MetaItem label="Trigger">{execution.trigger_type}</MetaItem>
                <MetaItem label="Попытки">
                    {execution.attempts} / {execution.max_attempts}
                </MetaItem>
                <MetaItem label="Создан">
                    {new Date(execution.created_at).toLocaleString()}
                    <span className="ml-1 text-xs text-muted-foreground">
                        ({formatRelative(execution.created_at)})
                    </span>
                </MetaItem>
                <MetaItem label="Начат">
                    {execution.started_at
                        ? new Date(execution.started_at).toLocaleString()
                        : "—"}
                </MetaItem>
                <MetaItem label="Завершён">
                    {execution.finished_at
                        ? new Date(execution.finished_at).toLocaleString()
                        : "—"}
                </MetaItem>
                <MetaItem label="Длительность">{duration ?? "—"}</MetaItem>
            </div>

            <div className="mb-4 flex gap-2">
                {canCancel && (
                    <Button
                        variant="destructive"
                        size="sm"
                        disabled={cancelMutation.isPending}
                        onClick={() => cancelMutation.mutate()}
                        data-testid="cancel-execution"
                    >
                        Cancel
                    </Button>
                )}
                {canReplay && (
                    <Button variant="outline" size="sm" asChild data-testid="replay-execution">
                        <Link to={`/workspaces/${wsId}/executions/${execution.id}/replay`}>
                            Replay
                        </Link>
                    </Button>
                )}
            </div>

            {execution.error && (
                <div
                    className="mb-6 rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-900"
                    data-testid="execution-error"
                >
                    {execution.error}
                </div>
            )}

            {hasPayload && (
                <div className="mb-6">
                    <JsonViewer
                        label="Trigger payload"
                        value={execution.trigger_payload}
                        testId="trigger-payload"
                    />
                </div>
            )}

            <h2 className="mb-2 text-sm font-medium">Шаги</h2>
            <div className="overflow-hidden rounded-md border bg-card">
                <table className="w-full text-sm">
                    <thead className="bg-muted/50 text-xs text-muted-foreground">
                        <tr>
                            <th className="w-6 px-3 py-2" />
                            <th className="px-3 py-2 text-left">Node</th>
                            <th className="px-3 py-2 text-left">Type</th>
                            <th className="px-3 py-2 text-left">Status</th>
                            <th className="px-3 py-2 text-left">Attempt</th>
                            <th className="px-3 py-2 text-left">Duration</th>
                        </tr>
                    </thead>
                    <tbody>
                        {execution.steps.map((step) => (
                            <StepRow key={step.id} step={step} />
                        ))}
                        {execution.steps.length === 0 && (
                            <tr>
                                <td
                                    colSpan={6}
                                    className="px-3 py-6 text-center text-sm text-muted-foreground"
                                >
                                    Шагов пока нет.
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
}