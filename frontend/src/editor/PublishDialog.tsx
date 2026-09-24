import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError } from "@/api/client";
import { listVersions, publishWorkflow, saveDraft } from "@/api/workflows";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { toBackendGraph, useEditorStore } from "@/stores/editorStore";

interface PublishDialogProps {
    wfId: string;
    open: boolean;
    onOpenChange: (open: boolean) => void;
}

/** Достаёт список ошибок валидации из ответа бэкенда.
 * Форма — detail: {message, errors: string[]} (см. POST /publish в workflows.py). */
function validationErrors(error: unknown): string[] | null {
    if (!(error instanceof ApiError) || error.status !== 422) return null;
    const detail = (error.body as { detail?: { errors?: string[] } })?.detail;
    return detail?.errors ?? [];
}

export function PublishDialog({ wfId, open, onOpenChange }: PublishDialogProps) {
    const queryClient = useQueryClient();
    const toast = useToast();
    const markClean = useEditorStore((state) => state.markClean);
    const [errors, setErrors] = useState<string[]>([]);

    const publishMutation = useMutation({
        mutationFn: () => publishWorkflow(wfId),
        onSuccess: async (result) => {
            toast.show(`Published v${result.version}`, "success");
            await queryClient.invalidateQueries({ queryKey: ["workflow", wfId] });
            await queryClient.invalidateQueries({ queryKey: ["workflows"] });
            await queryClient.invalidateQueries({ queryKey: ["versions", wfId] });
            setErrors([]);
            onOpenChange(false);
        },
        onError: (error) => {
            const invalid = validationErrors(error);
            if (invalid) {
                setErrors(invalid);
                return;
            }
            if (error instanceof ApiError && error.status === 409) {
                toast.show("Save a draft first", "error");
                onOpenChange(false);
                return;
            }
            toast.show(error instanceof Error ? error.message : "Не удалось опубликовать", "error");
        },
    });

    const saveAndPublishMutation = useMutation({
        mutationFn: async () => {
            const { nodes, edges } = useEditorStore.getState();
            await saveDraft(wfId, { graph: toBackendGraph(nodes, edges), change_note: null });
            return publishWorkflow(wfId);
        },
        onSuccess: async (result) => {
            markClean();
            toast.show(`Published v${result.version}`, "success");
            await queryClient.invalidateQueries({ queryKey: ["workflow", wfId] });
            await queryClient.invalidateQueries({ queryKey: ["workflows"] });
            await queryClient.invalidateQueries({ queryKey: ["versions", wfId] });
            setErrors([]);
            onOpenChange(false);
        },
        onError: (error) => {
            const invalid = validationErrors(error);
            if (invalid) {
                setErrors(invalid);
                return;
            }
            toast.show(error instanceof Error ? error.message : "Не удалось сохранить", "error");
        },
    });

    const isDirty = useEditorStore((state) => state.isDirty);

    // номер версии, которая уйдёт в публикацию — нужен для показа в диалоге
    const versionsQuery = useQuery({
        queryKey: ["versions", wfId],
        queryFn: () => listVersions(wfId),
        enabled: open,
    });
    const latestVersion = versionsQuery.data?.[0]?.version ?? null;

    const busy = publishMutation.isPending || saveAndPublishMutation.isPending;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent data-testid="publish-dialog">
                <DialogHeader>
                    <DialogTitle>Публикация</DialogTitle>
                </DialogHeader>

                {errors.length > 0 && (
                    <div
                        className="mb-3 rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900"
                        data-testid="publish-errors"
                    >
                        <p className="mb-1 font-medium">Граф невалиден:</p>
                        <ul className="list-inside list-disc">
                            {errors.map((message) => (
                                <li key={message}>{message}</li>
                            ))}
                        </ul>
                    </div>
                )}

                {isDirty ? (
                    <div className="flex flex-col gap-3">
                        <p className="text-sm text-muted-foreground">
                            Есть несохранённые изменения. Сохранить их перед публикацией?
                        </p>
                        <Button
                            onClick={() => saveAndPublishMutation.mutate()}
                            disabled={busy}
                            data-testid="save-and-publish"
                        >
                            {saveAndPublishMutation.isPending ? "…" : "Сохранить и опубликовать"}
                        </Button>
                        <Button
                            variant="outline"
                            onClick={() => publishMutation.mutate()}
                            disabled={busy || latestVersion === null}
                            data-testid="publish-last-saved"
                        >
                            {latestVersion === null
                                ? "Нет сохранённых версий"
                                : `Опубликовать последнюю сохранённую (v${latestVersion})`}
                        </Button>
                    </div>
                ) : (
                    <div className="flex flex-col gap-3">
                        <p className="text-sm text-muted-foreground">
                            {latestVersion === null
                                ? "Сохранённых версий нет."
                                : `Будет опубликована версия v${latestVersion}.`}
                        </p>
                        <Button
                            onClick={() => publishMutation.mutate()}
                            disabled={busy || latestVersion === null}
                            data-testid="publish-confirm"
                        >
                            {publishMutation.isPending ? "…" : "Опубликовать"}
                        </Button>
                    </div>
                )}

                <DialogFooter>
                    <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
                        Отмена
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}