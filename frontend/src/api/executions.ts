import { request } from "@/api/client";
import type { Execution, ExecutionDetail, ExecutionListResponse } from "@/types/execution";

export interface ListExecutionsParams {
    workflow_id?: string;
    status?: string;
    limit?: number;
    cursor?: string;
}

/** Список запусков workspace с фильтрами и keyset-пагинацией. */
export function listExecutions(
    wsId: string,
    params: ListExecutionsParams = {},
): Promise<ExecutionListResponse> {
    // пустые/undefined параметры не шлём: «status=» бэкенд поймёт как фильтр по ""
    const query = new URLSearchParams();
    if (params.workflow_id) query.set("workflow_id", params.workflow_id);
    if (params.status) query.set("status", params.status);
    if (params.limit !== undefined) query.set("limit", String(params.limit));
    if (params.cursor) query.set("cursor", params.cursor);

    const queryString = query.toString();
    const suffix = queryString ? `?${queryString}` : "";
    return request<ExecutionListResponse>(`/api/workspaces/${wsId}/executions${suffix}`);
}

export function getExecution(id: string): Promise<ExecutionDetail> {
    return request<ExecutionDetail>(`/api/executions/${id}`);
}

export function runWorkflow(
    workflowId: string,
    payload?: Record<string, unknown>,
): Promise<Execution> {
    return request<Execution>(`/api/workflows/${workflowId}/run`, {
        method: "POST",
        body: { payload: payload ?? {} },
    });
}

export function cancelExecution(id: string): Promise<Execution> {
    return request<Execution>(`/api/executions/${id}/cancel`, { method: "POST" });
}