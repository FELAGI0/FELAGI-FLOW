import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { listVersions } from "@/api/workflows";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { useEditorStore } from "@/stores/editorStore";
import type { WorkflowVersion } from "@/types/workflow";

const dateFormatter = new Intl.DateTimeFormat(undefined, {
    dateStyle: "short",
    timeStyle: "short",
});

interface VersionHistoryPanelProps {
    wfId: string;
    open: boolean;
    onOpenChange: (open: boolean) => void;
    publishedVersionId: string | null;
}

export function VersionHistoryPanel({
    wfId,
    open,
    onOpenChange,
    publishedVersionId,
}: VersionHistoryPanelProps) {
    const reset = useEditorStore((state) => state.reset);
    const isDirty = useEditorStore((state) => state.isDirty);
    const [pending, setPending] = useState<WorkflowVersion | null>(null);

    const { data: versions, isLoading } = useQuery({
        queryKey: ["versions", wfId],
        queryFn: () => listVersions(wfId),
        enabled: open,
    });

    function applyVersion(version: WorkflowVersion) {
        reset(version.graph);
        // загрузка версии в канвас — это ещё не сохранённое изменение
        useEditorStore.setState({ isDirty: true });
        setPending(null);
        onOpenChange(false);
    }

    function onSelect(version: WorkflowVersion) {
        if (isDirty) setPending(version);
        else applyVersion(version);
    }

    const latest = versions?.[0];

    return (
        <>
            <Dialog open={open} onOpenChange={onOpenChange}>
                <DialogContent data-testid="versions-dialog">
                    <DialogHeader>
                        <DialogTitle>Версии</DialogTitle>
                    </DialogHeader>

                    {isLoading && <p className="text-sm text-muted-foreground">Загрузка…</p>}
                    {!isLoading && (versions ?? []).length === 0 && (
                        <p className="text-sm text-muted-foreground">
                            Версий пока нет — сохраните черновик.
                        </p>
                    )}

                    <ul className="flex max-h-80 flex-col gap-2 overflow-y-auto">
                        {(versions ?? []).map((version) => (
                            <li key={version.id}>
                                <button
                                    type="button"
                                    onClick={() => onSelect(version)}
                                    data-testid={`version-${version.version}`}
                                    className={cn(
                                        "flex w-full items-center justify-between gap-3 rounded-md border px-3 py-2 text-left text-sm hover:bg-accent",
                                    )}
                                >
                                    <span className="flex flex-col">
                                        <span className="font-medium">v{version.version}</span>
                                        {version.change_note && (
                                            <span className="text-xs text-muted-foreground">
                                                {version.change_note}
                                            </span>
                                        )}
                                        <span className="text-xs text-muted-foreground">
                                            {dateFormatter.format(new Date(version.created_at))}
                                        </span>
                                    </span>
                                    <span className="flex shrink-0 gap-1">
                                        {version.id === publishedVersionId && (
                                            <span
                                                className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] text-emerald-900"
                                                data-testid="badge-published"
                                            >
                                                published
                                            </span>
                                        )}
                                        {version.id === latest?.id && (
                                            <span
                                                className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] text-slate-700"
                                                data-testid="badge-current-draft"
                                            >
                                                current draft
                                            </span>
                                        )}
                                    </span>
                                </button>
                            </li>
                        ))}
                    </ul>
                </DialogContent>
            </Dialog>

            <Dialog open={pending !== null} onOpenChange={(next) => !next && setPending(null)}>
                <DialogContent data-testid="unsaved-dialog">
                    <DialogHeader>
                        <DialogTitle>Несохранённые изменения</DialogTitle>
                    </DialogHeader>
                    <p className="text-sm text-muted-foreground">
                        Несохранённые изменения будут потеряны. Продолжить?
                    </p>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setPending(null)}>
                            Отмена
                        </Button>
                        <Button
                            onClick={() => pending && applyVersion(pending)}
                            data-testid="confirm-load-version"
                        >
                            Загрузить
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </>
    );
}