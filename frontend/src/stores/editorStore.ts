import {
    addEdge,
    applyEdgeChanges,
    applyNodeChanges,
    type Connection,
    type Edge,
    type EdgeChange,
    type Node,
    type NodeChange,
} from "@xyflow/react";
import { create } from "zustand";

import type { WorkflowGraph, WorkflowNodeData } from "@/types/workflow";

/** Узел на канвасе: React Flow Node с нашим data-пейлоадом. */
export type EditorNode = Node<WorkflowNodeData & Record<string, unknown>>;

interface EditorState {
    nodes: EditorNode[];
    edges: Edge[];
    selectedNodeId: string | null;
    isDirty: boolean;
    onNodesChange: (changes: NodeChange<EditorNode>[]) => void;
    onEdgesChange: (changes: EdgeChange[]) => void;
    onConnect: (connection: Connection) => void;
    addNodeFromPalette: (type: string, label: string, position: { x: number; y: number }) => string;
    updateNodeParams: (id: string, params: Record<string, unknown>) => void;
    setSelectedNode: (id: string | null) => void;
    reset: (graph: WorkflowGraph) => void;
    markClean: () => void;
}

let nodeCounter = 0;

export function nextNodeId(): string {
    nodeCounter += 1;
    return `node_${nodeCounter}_${Math.random().toString(36).slice(2, 8)}`;
}

export const useEditorStore = create<EditorState>((set) => ({
    nodes: [],
    edges: [],
    selectedNodeId: null,
    isDirty: false,

    onNodesChange: (changes) =>
        set((state) => ({
            nodes: applyNodeChanges<EditorNode>(changes, state.nodes),
            isDirty: true,
        })),

    onEdgesChange: (changes) =>
        set((state) => ({ edges: applyEdgeChanges(changes, state.edges), isDirty: true })),

    onConnect: (connection) =>
        set((state) => ({ edges: addEdge(connection, state.edges), isDirty: true })),

    addNodeFromPalette: (type, label, position) => {
        const id = nextNodeId();
        set((state) => ({
            nodes: [
                ...state.nodes,
                { id, type: "base", position, data: { type, label, params: {} } },
            ],
            isDirty: true,
        }));
        return id;
    },

    updateNodeParams: (id, params) =>
        set((state) => ({
            nodes: state.nodes.map((node) =>
                node.id === id ? { ...node, data: { ...node.data, params } } : node,
            ),
            isDirty: true,
        })),

    setSelectedNode: (id) => set({ selectedNodeId: id }),

    reset: (graph) =>
        set({
            nodes: graph.nodes.map((node) => ({
                id: node.id,
                type: "base",
                position: node.position,
                data: { type: node.type, label: node.type, params: node.params },
            })),
            edges: graph.edges.map((edge) => ({
                id: edge.id,
                source: edge.source,
                target: edge.target,
                sourceHandle: edge.sourceHandle ?? null,
                targetHandle: edge.targetHandle ?? null,
            })),
            selectedNodeId: null,
            isDirty: false,
        }),

    markClean: () => set({ isDirty: false }),
}));

/** Сериализация канваса в формат бэкенда (Node = {id, type, params, position}). */
export function toBackendGraph(nodes: EditorNode[], edges: Edge[]): WorkflowGraph {
    return {
        nodes: nodes.map((node) => ({
            id: node.id,
            type: node.data.type,
            params: node.data.params,
            position: { x: node.position.x, y: node.position.y },
        })),
        edges: edges.map((edge) => ({
            id: edge.id,
            source: edge.source,
            target: edge.target,
            sourceHandle: edge.sourceHandle ?? undefined,
            targetHandle: edge.targetHandle ?? undefined,
        })),
        layout: {},
    };
}