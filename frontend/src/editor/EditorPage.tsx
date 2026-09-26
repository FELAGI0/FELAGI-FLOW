import { ReactFlowProvider } from "@xyflow/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { ApiError } from "@/api/client";
import { runWorkflow } from "@/api/executions";
import { getWorkflow, listVersions, patchWorkflow, saveDraft } from "@/api/workflows";
import { useToast } from "@/components/ui/toast";
import { FlowCanvas } from "@/editor/FlowCanvas";
import { NodePalette } from "@/editor/NodePalette";
import { ParamsPanel } from "@/editor/ParamsPanel";
import { PublishDialog } from "@/editor/PublishDialog";
import { Toolbar } from "@/editor/Toolbar";
import { VersionHistoryPanel } from "@/editor/VersionHistoryPanel";
import { toBackendGraph, useEditorStore } from "@/stores/editorStore";

const EMPTY_GRAPH = { nodes: [], edges: [], layout: {} };

export function EditorPage() {
    const { wsId = "", wfId = "" } = useParams();
    const navigate = useNavigate();
    const queryClient = useQueryClient();
    const toast = useToast();
    const reset = useEditorStore((state) => state.reset);
    const markClean = useEditorStore((state) => state.markClean);
    const isDirty = useEditorStore((state) => state.isDirty);

    const [name, setName] = useState("");
    const [versionsOpen, setVersionsOpen] = useState(false);
    const [publishOpen, setPublishOpen] = useState(false);
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

    // предупреждение при уходе со страницы с несохранёнными изменениями
    useEffect(() => {
        function onBeforeUnload(event: BeforeUnloadEvent) {
            if (!isDirty) return;
            event.preventDefault();
        }
        window.addEventListener("beforeunload", onBeforeUnload);
        return () => window.removeEventListener("beforeunload", onBeforeUnload);
    }, [isDirty]);

    const renameMutation = useMutation({
        mutationFn: (nextName: string) => patchWorkflow(wfId, { name: nextName }),
    });

    const saveMutation = useMutation({
        mutationFn: () => {
            const { nodes, edges } = useEditorStore.getState();
            return saveDraft(wfId, { graph: toBackendGraph(nodes, edges), change_note: null });
        },
        onSuccess: async (version) => {
            markClean();
            toast.show(`Saved v${version.version}`, "success");
            await queryClient.invalidateQueries({ queryKey: ["versions", wfId] });
            await queryClient.invalidateQueries({ queryKey: ["workflows"] });
        },
        onError: (error) => {
            if (error instanceof ApiError && error.status === 422) {
                const detail = error.body as { detail?: { errors?: string[] } };
                toast.show(
                    `Граф невалиден: ${(detail.detail?.errors ?? []).join("; ")}`,
                    "error",
                );
            } else {
                toast.show(error instanceof Error ? error.message : "Не удалось сохранить", "error");
            }
        },
    });

    const latestVersion = versionsQuery.data?.[0]?.version ?? null;

    const runMutation = useMutation({
        mutationFn: () => runWorkflow(wfId),
        onSuccess: (execution) => {
            // сразу открываем детали запуска — там live/статус (5.C.2 добавит ленту)
            navigate(`/workspaces/${wsId}/executions/${execution.id}`);
        },
        onError: (error) => {
            // 409 — workflow не опубликован: подсказка вместо общей ошибки
            if (error instanceof ApiError && error.status === 409) {
                toast.show("Workflow не опубликован — сначала опубликуйте", "error");
            } else {
                toast.show(error instanceof Error ? error.message : "Не удалось запустить", "error");
            }
        },
    });

    return (
        <div className="flex h-screen flex-col">
            <Toolbar
                workflowName={name}
                status={workflowQuery.data?.status ?? "draft"}
                lastVersion={latestVersion}
                isDirty={isDirty}
                isSaving={saveMutation.isPending}
                isRunning={runMutation.isPending}
                onRename={(next) => {
                    setName(next);
                    renameMutation.mutate(next);
                }}
                onSave={() => saveMutation.mutate()}
                onRun={() => runMutation.mutate()}
                onOpenVersions={() => setVersionsOpen(true)}
                onOpenPublish={() => setPublishOpen(true)}
                backTo={`/workspaces/${wsId}/workflows`}
            />

            <div className="flex min-h-0 flex-1">
                <NodePalette />
                <div className="min-w-0 flex-1">
                    <ReactFlowProvider>
                        <FlowCanvas />
                    </ReactFlowProvider>
                </div>
                <ParamsPanel />
            </div>

            <VersionHistoryPanel
                wfId={wfId}
                open={versionsOpen}
                onOpenChange={setVersionsOpen}
                publishedVersionId={workflowQuery.data?.published_version_id ?? null}
            />
            <PublishDialog wfId={wfId} open={publishOpen} onOpenChange={setPublishOpen} />
        </div>
    );
}