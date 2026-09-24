import { ReactFlowProvider } from "@xyflow/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";

import { ApiError } from "@/api/client";
import { getWorkflow, listVersions, patchWorkflow, publishWorkflow, saveDraft } from "@/api/workflows";
import { FlowCanvas } from "@/editor/FlowCanvas";
import { NodePalette } from "@/editor/NodePalette";
import { ParamsPanel } from "@/editor/ParamsPanel";
import { Toolbar } from "@/editor/Toolbar";
import { toBackendGraph, useEditorStore } from "@/stores/editorStore";

const EMPTY_GRAPH = { nodes: [], edges: [], layout: {} };

export function EditorPage() {
    const { wsId = "", wfId = "" } = useParams();
    const reset = useEditorStore((state) => state.reset);
    const markClean = useEditorStore((state) => state.markClean);

    const [name, setName] = useState("");
    const [banner, setBanner] = useState<string | null>(null);
    // защита от повторного reset: канвас загружается один раз на открытие
    const loadedRef = useRef<string | null>(null);

    const workflowQuery = useQuery({
        queryKey: ["workflow", wfId],
        queryFn: () => getWorkflow(wfId),
    });

    const versionsQuery = useQuery({
        queryKey: ["versions", wfId],
        queryFn: () => listVersions(wfId),
    });

    useEffect(() => {
        if (workflowQuery.data) setName(workflowQuery.data.name);
    }, [workflowQuery.data]);

    useEffect(() => {
        if (versionsQuery.isSuccess && loadedRef.current !== wfId) {
            loadedRef.current = wfId;
            const latest = versionsQuery.data[0];
            reset(latest ? latest.graph : EMPTY_GRAPH);
        }
    }, [versionsQuery.isSuccess, versionsQuery.data, reset, wfId]);

    const renameMutation = useMutation({
        mutationFn: (nextName: string) => patchWorkflow(wfId, { name: nextName }),
    });

    const saveMutation = useMutation({
        mutationFn: () => {
            const { nodes, edges } = useEditorStore.getState();
            return saveDraft(wfId, { graph: toBackendGraph(nodes, edges), change_note: null });
        },
        onSuccess: () => {
            markClean();
            setBanner(null);
        },
        onError: (error) => {
            if (error instanceof ApiError && error.status === 422) {
                const detail = error.body as { detail?: { errors?: string[] } };
                setBanner(`Граф невалиден: ${(detail.detail?.errors ?? []).join("; ")}`);
            } else {
                setBanner(error instanceof Error ? error.message : "Не удалось сохранить");
            }
        },
    });

    const publishMutation = useMutation({
        mutationFn: () => publishWorkflow(wfId),
        onSuccess: (result) => setBanner(`Опубликовано: версия ${result.version}`),
        onError: (error) => {
            if (error instanceof ApiError && error.status === 422) {
                const detail = error.body as { detail?: { errors?: string[] } };
                setBanner(`Граф невалиден: ${(detail.detail?.errors ?? []).join("; ")}`);
            } else if (error instanceof ApiError && error.status === 409) {
                setBanner("Нет версий для публикации — сначала сохраните черновик");
            } else {
                setBanner(error instanceof Error ? error.message : "Не удалось опубликовать");
            }
        },
    });

    const isDirty = useEditorStore((state) => state.isDirty);

    return (
        <div className="flex h-screen flex-col">
            <Toolbar
                workflowName={name}
                status={workflowQuery.data?.status ?? "draft"}
                isDirty={isDirty}
                isSaving={saveMutation.isPending}
                isPublishing={publishMutation.isPending}
                onRename={(next) => {
                    setName(next);
                    renameMutation.mutate(next);
                }}
                onSave={() => saveMutation.mutate()}
                onPublish={() => publishMutation.mutate()}
                backTo={`/workspaces/${wsId}/workflows`}
            />

            {banner && (
                <div
                    className="border-b bg-amber-50 px-4 py-2 text-sm text-amber-900"
                    data-testid="editor-banner"
                >
                    {banner}
                </div>
            )}

            <div className="flex min-h-0 flex-1">
                <NodePalette />
                <div className="min-w-0 flex-1">
                    <ReactFlowProvider>
                        <FlowCanvas />
                    </ReactFlowProvider>
                </div>
                <ParamsPanel />
            </div>
        </div>
    );
}