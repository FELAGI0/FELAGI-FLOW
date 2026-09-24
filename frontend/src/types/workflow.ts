export interface NodePosition {
    x: number;
    y: number;
}

export interface WorkflowNodeData {
    type: string;
    params: Record<string, unknown>;
    label: string;
}

/** Проводной формат узла: совпадает с backend-схемой Node (без вложенного data). */
export interface WorkflowNode {
    id: string;
    type: string;
    params: Record<string, unknown>;
    position: NodePosition;
}

export interface WorkflowEdge {
    id: string;
    source: string;
    target: string;
    sourceHandle?: string | undefined;
    targetHandle?: string | undefined;
}

export interface WorkflowGraph {
    nodes: WorkflowNode[];
    edges: WorkflowEdge[];
    layout?: Record<string, unknown>;
}

export interface WorkflowVersion {
    id: string;
    workflow_id: string;
    version: number;
    graph: WorkflowGraph;
    change_note: string | null;
    created_at: string;
}

export interface Workflow {
    id: string;
    workspace_id: string;
    name: string;
    status: "draft" | "active" | "paused";
    published_version_id: string | null;
    created_at: string;
    updated_at: string;
}

export interface Workspace {
    id: string;
    name: string;
    slug: string;
    plan: string;
    current_user_role: string;
    created_at: string;
}

export interface InviteResponse {
    id: string;
    email: string;
    role: string;
    expires_at: string;
    invite_url: string;
}

export interface MemberResponse {
    user_id: string;
    email: string;
    name: string | null;
    role: string;
    joined_at: string;
}
