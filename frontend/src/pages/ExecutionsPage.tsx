import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { cancelExecution, listExecutions } from "@/api/executions";
import { listWorkflows } from "@/api/workflows";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { formatDuration, formatRelative, shortId } from "@/lib/time";
import { isTerminalStatus, type Execution } from "@/types/execution";

const ALL = "all";
const PAGE_LIMIT = 20;

const STATUS_OPTIONS = ["queued", "running", "succeeded", "failed", "dead", "canceled"];

function ExecutionRow({
    execution,
    wsId,
    onCancel,
    cancelling,
}: {
    execution: Execution;
    wsId: string;
    onCancel: (execution: Execution) => void;
    cancelling: boolean;
}) {
    // отменять можно только незавершённые: queued/running
    const canCancel = !isTerminalStatus(execution.status);
    const duration = formatDuration(execution.started_at, execution.finished_at);

    return (
        <tr className="border-b last:border-0" data-testid={`execution-row-${execution.id}`}>
            <td className="px-3 py-2 font-mono text-xs">
                <Link
                    to={`/workspaces/${wsId}/executions/${execution.id}`}
                    className="text-primary hover:underline"
                >
                    {shortId(execution.id)}
                </Link>
            </td>
            <td className="px-3 py-2 font-mono text-xs">
                <Link
                    to={`/workspaces/${wsId}/workflows/${execution.workflow_id}/edit`}
                    className="text-primary hover:underline"
                >
                    {shortId(execution.workflow_id)}
                </Link>
            </td>
            <td className="px-3 py-2">
                <StatusBadge status={execution.status} />
            </td>
            <td className="px-3 py-2 text-xs text-muted-foreground">{execution.trigger_type}</td>
            <td className="px-3 py-2 text-xs text-muted-foreground">
                {formatRelative(execution.created_at)}
            </td>
            <td className="px-3 py-2 text-xs text-muted-foreground">{duration ?? "—"}</td>
            <td className="px-3 py-2">
                <div className="flex justify-end gap-2">
                    {canCancel && (
                        <Button
                            variant="outline"
                            size="sm"
                            disabled={cancelling}
                            onClick={() => onCancel(execution)}
                            data-testid={`cancel-${execution.id}`}
                        >
                            Cancel
                        </Button>
                    )}
                    <Button variant="ghost" size="sm" asChild>
                        <Link to={`/workspaces/${wsId}/executions/${execution.id}`}>View</Link>
                    </Button>
                </div>
            </td>
        </tr>
    );
}

export function ExecutionsPage() {
    const { wsId = "" } = useParams();
    const [searchParams, setSearchParams] = useSearchParams();
    const queryClient = useQueryClient();
    const toast = useToast();

    const workflowFilter = searchParams.get("workflow_id") ?? "";
    const statusFilter = searchParams.get("status") ?? ALL;

    const workflowsQuery = useQuery({
        queryKey: ["workflows", wsId],
        queryFn: () => listWorkflows(wsId),
    });

    const executionsQuery = useInfiniteQuery({
        queryKey: ["executions", wsId, workflowFilter, statusFilter],
        queryFn: ({ pageParam }) =>
            listExecutions(wsId, {
                workflow_id: workflowFilter || undefined,
                status: statusFilter === ALL ? undefined : statusFilter,
                limit: PAGE_LIMIT,
                cursor: pageParam ?? undefined,
            }),
        initialPageParam: null as string | null,
        getNextPageParam: (lastPage) => lastPage.next_cursor,
        // автообновление, пока есть незавершённые запуски (иначе лишний трафик)
        refetchInterval: (query) => {
            const items = query.state.data?.pages.flatMap((page) => page.items) ?? [];
            return items.some((execution) => !isTerminalStatus(execution.status)) ? 3000 : false;
        },
    });

    const items = (executionsQuery.data?.pages ?? []).flatMap((page) => page.items);

    const cancelMutation = useMutation({
        mutationFn: (execution: Execution) => cancelExecution(execution.id),
        onSuccess: async () => {
            toast.show("Запуск отменён", "success");
            await queryClient.invalidateQueries({ queryKey: ["executions"] });
        },
        onError: (error) =>
            toast.show(error instanceof Error ? error.message : "Не удалось отменить", "error"),
    });

    function setFilter(key: "workflow_id" | "status", value: string) {
        const next = new URLSearchParams(searchParams);
        if (value === "" || value === ALL) next.delete(key);
        else next.set(key, value);
        setSearchParams(next);
    }

    return (
        <div className="mx-auto max-w-6xl p-8">
            <div className="mb-6 flex items-center justify-between">
                <div>
                    <Link
                        to={`/workspaces/${wsId}/workflows`}
                        className="text-sm text-muted-foreground hover:underline"
                    >
                        ← Workflows
                    </Link>
                    <h1 className="text-xl font-semibold">Запуски</h1>
                </div>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={() => executionsQuery.refetch()}
                    disabled={executionsQuery.isFetching && !executionsQuery.isFetchingNextPage}
                    data-testid="refresh-executions"
                >
                    {executionsQuery.isFetching && !executionsQuery.isFetchingNextPage
                        ? "Обновление…"
                        : "Обновить"}
                </Button>
            </div>

            <div className="mb-4 flex flex-wrap gap-3">
                <div className="w-56">
                    <Select
                        value={workflowFilter || ALL}
                        onValueChange={(value) => setFilter("workflow_id", value)}
                    >
                        <SelectTrigger data-testid="workflow-filter" aria-label="Фильтр workflow">
                            <SelectValue placeholder="Все workflow" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value={ALL}>Все workflow</SelectItem>
                            {(workflowsQuery.data ?? []).map((workflow) => (
                                <SelectItem key={workflow.id} value={workflow.id}>
                                    {workflow.name}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>

                <div className="w-40">
                    <Select
                        value={statusFilter}
                        onValueChange={(value) => setFilter("status", value)}
                    >
                        <SelectTrigger data-testid="status-filter" aria-label="Фильтр статуса">
                            <SelectValue placeholder="Все статусы" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value={ALL}>Все статусы</SelectItem>
                            {STATUS_OPTIONS.map((status) => (
                                <SelectItem key={status} value={status}>
                                    {status}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </div>
            </div>

            {executionsQuery.isLoading && (
                <p className="text-sm text-muted-foreground">Загрузка…</p>
            )}

            <div className="overflow-hidden rounded-md border bg-card">
                <table className="w-full text-sm">
                    <thead className="bg-muted/50 text-xs text-muted-foreground">
                        <tr>
                            <th className="px-3 py-2 text-left">ID</th>
                            <th className="px-3 py-2 text-left">Workflow</th>
                            <th className="px-3 py-2 text-left">Status</th>
                            <th className="px-3 py-2 text-left">Trigger</th>
                            <th className="px-3 py-2 text-left">Started</th>
                            <th className="px-3 py-2 text-left">Duration</th>
                            <th className="px-3 py-2" />
                        </tr>
                    </thead>
                    <tbody>
                        {items.map((execution) => (
                            <ExecutionRow
                                key={execution.id}
                                execution={execution}
                                wsId={wsId}
                                onCancel={(target) => cancelMutation.mutate(target)}
                                cancelling={cancelMutation.isPending}
                            />
                        ))}
                        {!executionsQuery.isLoading && items.length === 0 && (
                            <tr>
                                <td
                                    colSpan={7}
                                    className="px-3 py-6 text-center text-sm text-muted-foreground"
                                >
                                    Запусков пока нет.
                                </td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>

            {executionsQuery.hasNextPage && (
                <div className="mt-4 flex justify-center">
                    <Button
                        variant="outline"
                        size="sm"
                        onClick={() => executionsQuery.fetchNextPage()}
                        disabled={executionsQuery.isFetchingNextPage}
                        data-testid="load-more"
                    >
                        {executionsQuery.isFetchingNextPage ? "Загрузка…" : "Загрузить ещё"}
                    </Button>
                </div>
            )}
        </div>
    );
}