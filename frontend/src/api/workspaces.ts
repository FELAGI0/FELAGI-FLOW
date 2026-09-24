import { request } from "@/api/client";
import type { Workspace } from "@/types/workflow";

export function listWorkspaces(): Promise<Workspace[]> {
    return request<Workspace[]>("/api/workspaces");
}

export function getWorkspace(id: string): Promise<Workspace> {
    return request<Workspace>(`/api/workspaces/${id}`);
}