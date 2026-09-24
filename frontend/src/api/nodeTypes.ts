import { request } from "@/api/client";

export interface NodeTypeSchema {
    type: string;
    label: string;
    category: "trigger" | "action" | "transform" | "logic" | "debug";
    // JSON-Schema из Pydantic model_json_schema() на бэкенде
    params_schema: {
        properties?: Record<string, JsonSchemaProperty>;
        required?: string[];
    };
    outputs: string[];
}

export interface JsonSchemaProperty {
    type?: string;
    title?: string;
    description?: string;
    default?: unknown;
    enum?: unknown[];
    anyOf?: JsonSchemaProperty[];
    items?: JsonSchemaProperty;
    minimum?: number;
    maximum?: number;
}

export function getNodeTypes(): Promise<NodeTypeSchema[]> {
    return request<NodeTypeSchema[]>("/api/node-types");
}