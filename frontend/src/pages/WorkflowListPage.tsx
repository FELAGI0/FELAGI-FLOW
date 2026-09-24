import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { createWorkflow, listWorkflows } from "@/api/workflows";
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

export function WorkflowListPage() {
    const { wsId = "" } = useParams();
    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const [open, setOpen] = useState(false);
    const [name, setName] = useState("");

    const { data: workflows, isLoading } = useQuery({
        queryKey: ["workflows", wsId],
        queryFn: () => listWorkflows(wsId),
    });

    const createMutation = useMutation({
        mutationFn: (workflowName: string) => createWorkflow(wsId, workflowName),
        onSuccess: async (workflow) => {
            await queryClient.invalidateQueries({ queryKey: ["workflows", wsId] });
            setOpen(false);
            setName("");
            navigate(`/workspaces/${wsId}/workflows/${workflow.id}/edit`);
        },
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
                <Button size="sm" onClick={() => setOpen(true)}>
                    Создать
                </Button>
            </div>

            {isLoading && <p className="text-sm text-muted-foreground">Загрузка…</p>}

            <ul className="flex flex-col gap-2">
                {(workflows ?? []).map((workflow) => (
                    <li key={workflow.id}>
                        <Link
                            to={`/workspaces/${wsId}/workflows/${workflow.id}/edit`}
                            className="flex items-center justify-between rounded-md border bg-card px-4 py-3 hover:bg-accent"
                        >
                            <span className="font-medium">{workflow.name}</span>
                            <span className="text-xs text-muted-foreground">{workflow.status}</span>
                        </Link>
                    </li>
                ))}
                {!isLoading && (workflows ?? []).length === 0 && (
                    <li className="text-sm text-muted-foreground">
                        Пока нет workflows — создайте первый.
                    </li>
                )}
            </ul>

            <Dialog open={open} onOpenChange={setOpen}>
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
                        />
                    </div>
                    <DialogFooter>
                        <Button
                            disabled={name.trim().length === 0 || createMutation.isPending}
                            onClick={() => createMutation.mutate(name.trim())}
                        >
                            Создать
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}