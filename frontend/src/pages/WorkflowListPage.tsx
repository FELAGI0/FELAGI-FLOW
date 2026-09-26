import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { createWorkflow, deleteWorkflow, listVersions, listWorkflows } from "@/api/workflows";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import type { Workflow } from "@/types/workflow";

const STATUS_CLASSES: Record<string, string> = {
    draft: "border-slate-300 text-slate-600",
    active: "border-emerald-300 bg-emerald-50 text-emerald-900",
    paused: "border-amber-300 bg-amber-50 text-amber-900",
};

/** Номер опубликованной версии: GET /versions + published_version_id → номер. */
function usePublishedVersion(workflow: Workflow | null) {
    return useQuery({
        queryKey: ["versions", workflow?.id],
        queryFn: () => listVersions(workflow?.id ?? ""),
        enabled: Boolean(workflow?.id),
        select: (versions) =>
            versions.find((version) => version.id === workflow?.published_version_id)?.version ??
            null,
    });
}

function WorkflowRow({
    workflow,
    wsId,
    onDelete,
}: {
    workflow: Workflow;
    wsId: string;
    onDelete: (workflow: Workflow) => void;
}) {
    const { data: publishedVersion } = usePublishedVersion(workflow);

    return (
        <li
            className="flex items-center gap-3 rounded-md border bg-card px-4 py-3"
            data-testid={`workflow-row-${workflow.name}`}
        >
            <div className="flex min-w-0 flex-1 flex-col">
                <span className="truncate font-medium">{workflow.name}</span>
            </div>

            <span
                className={`rounded-full border px-2 py-0.5 text-xs ${STATUS_CLASSES[workflow.status] ?? ""}`}
                data-testid={`workflow-status-${workflow.name}`}
            >
                {workflow.status}
            </span>

            <span
                className="w-12 text-center text-xs text-muted-foreground"
                data-testid={`workflow-published-${workflow.name}`}
            >
                {publishedVersion === null || publishedVersion === undefined
                    ? "—"
                    : `v${publishedVersion}`}
            </span>

            <Button variant="outline" size="sm" asChild>
                <Link to={`/workspaces/${wsId}/executions?workflow_id=${workflow.id}`}>
                    Запуски
                </Link>
            </Button>
            <Button variant="outline" size="sm" asChild>
                <Link to={`/workspaces/${wsId}/workflows/${workflow.id}/edit`}>Редактировать</Link>
            </Button>
            <Button
                variant="ghost"
                size="sm"
                onClick={() => onDelete(workflow)}
                data-testid={`workflow-delete-${workflow.name}`}
            >
                Удалить
            </Button>
        </li>
    );
}

export function WorkflowListPage() {
    const { wsId = "" } = useParams();
    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const toast = useToast();

    const [createOpen, setCreateOpen] = useState(false);
    const [name, setName] = useState("");
    const [pendingDelete, setPendingDelete] = useState<Workflow | null>(null);

    const { data: workflows, isLoading } = useQuery({
        queryKey: ["workflows", wsId],
        queryFn: () => listWorkflows(wsId),
    });

    const createMutation = useMutation({
        mutationFn: (workflowName: string) => createWorkflow(wsId, workflowName),
        onSuccess: async (workflow) => {
            await queryClient.invalidateQueries({ queryKey: ["workflows", wsId] });
            setCreateOpen(false);
            setName("");
            navigate(`/workspaces/${wsId}/workflows/${workflow.id}/edit`);
        },
        onError: (error) =>
            toast.show(error instanceof Error ? error.message : "Не удалось создать", "error"),
    });

    const deleteMutation = useMutation({
        mutationFn: (workflowId: string) => deleteWorkflow(workflowId),
        onSuccess: async () => {
            await queryClient.invalidateQueries({ queryKey: ["workflows", wsId] });
            setPendingDelete(null);
            toast.show("Workflow удалён", "success");
        },
        onError: (error) =>
            toast.show(error instanceof Error ? error.message : "Не удалось удалить", "error"),
    });

    return (
        <div className="mx-auto max-w-3xl p-8">
            <div className="mb-6 flex items-center justify-between">
                <div>
                    <Link to="/workspaces" className="text-sm text-muted-foreground hover:underline">
                        ← Workspace&apos;ы
                    </Link>
                    <h1 className="text-xl font-semibold">Workflows</h1>
                </div>
                <Button size="sm" onClick={() => setCreateOpen(true)} data-testid="create-workflow">
                    Создать
                </Button>
            </div>

            {isLoading && <p className="text-sm text-muted-foreground">Загрузка…</p>}

            <ul className="flex flex-col gap-2">
                {(workflows ?? []).map((workflow) => (
                    <WorkflowRow
                        key={workflow.id}
                        workflow={workflow}
                        wsId={wsId}
                        onDelete={setPendingDelete}
                    />
                ))}
                {!isLoading && (workflows ?? []).length === 0 && (
                    <li className="text-sm text-muted-foreground">
                        Пока нет workflows — создайте первый.
                    </li>
                )}
            </ul>

            <Dialog open={createOpen} onOpenChange={setCreateOpen}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Новый workflow</DialogTitle>
                    </DialogHeader>
                    <div className="flex flex-col gap-1.5">
                        <Label htmlFor="wf-name">Название</Label>
                        <Input
                            id="wf-name"
                            value={name}
                            onChange={(event) => setName(event.target.value)}
                            placeholder="My workflow"
                            data-testid="workflow-name-input"
                        />
                    </div>
                    <DialogFooter>
                        <Button
                            disabled={name.trim().length === 0 || createMutation.isPending}
                            onClick={() => createMutation.mutate(name.trim())}
                            data-testid="confirm-create-workflow"
                        >
                            Создать
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <Dialog open={pendingDelete !== null} onOpenChange={(next) => !next && setPendingDelete(null)}>
                <DialogContent data-testid="delete-dialog">
                    <DialogHeader>
                        <DialogTitle>Удалить workflow?</DialogTitle>
                    </DialogHeader>
                    <p className="text-sm text-muted-foreground">
                        «{pendingDelete?.name}» и все его версии будут удалены. Это необратимо.
                    </p>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setPendingDelete(null)}>
                            Отмена
                        </Button>
                        <Button
                            variant="destructive"
                            onClick={() => pendingDelete && deleteMutation.mutate(pendingDelete.id)}
                            disabled={deleteMutation.isPending}
                            data-testid="confirm-delete-workflow"
                        >
                            Удалить
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}