import { request } from "@/api/client";
import type { Workflow, WorkflowGraph, WorkflowVersion } from "@/types/workflow";

export function listWorkflows(wsId: string): Promise<Workflow[]> {
    return request<Workflow[]>(`/api/workspaces/${wsId}/workflows`);
}

export function getWorkflow(id: string): Promise<Workflow> {
    return request<Workflow>(`/api/workflows/${id}`);
}

export function createWorkflow(wsId: string, name: string): Promise<Workflow> {
    return request<Workflow>(`/api/workspaces/${wsId}/workflows`, {
        method: "POST",
        body: { name },
    });
}

export function patchWorkflow(
    id: string,
    patch: { name?: string; status?: "draft" | "paused" },
): Promise<Workflow> {
    return request<Workflow>(`/api/workflows/${id}`, { method: "PATCH", body: patch });
}

export function deleteWorkflow(id: string): Promise<void> {
    return request<void>(`/api/workflows/${id}`, { method: "DELETE" });
}

export function listVersions(id: string): Promise<WorkflowVersion[]> {
    return request<WorkflowVersion[]>(`/api/workflows/${id}/versions`);
}

export function getVersion(id: string, version: number): Promise<WorkflowVersion> {
    return request<WorkflowVersion>(`/api/workflows/${id}/versions/${version}`);
}

export function saveDraft(
    id: string,
    payload: { graph: WorkflowGraph; change_note: string | null },
): Promise<WorkflowVersion> {
    return request<WorkflowVersion>(`/api/workflows/${id}/versions`, {
        method: "POST",
        body: payload,
    });
}

export interface PublishResult {
    workflow_id: string;
    published_version_id: string;
    version: number;
}

export function publishWorkflow(id: string): Promise<PublishResult> {
    return request<PublishResult>(`/api/workflows/${id}/publish`, { method: "POST" });
}