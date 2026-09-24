import type { Edge } from "@xyflow/react";
import { beforeEach, describe, expect, it } from "vitest";

import { nextNodeId, toBackendGraph, useEditorStore } from "@/stores/editorStore";
import type { WorkflowGraph } from "@/types/workflow";

function store() {
    return useEditorStore.getState();
}

beforeEach(() => {
    store().reset({ nodes: [], edges: [], layout: {} });
});

describe("editorStore: добавление и удаление узлов", () => {
    it("addNodeFromPalette добавляет узел с типом, лейблом и позицией", () => {
        const id = store().addNodeFromPalette("transform_set", "Set", { x: 10, y: 20 });
        const nodes = store().nodes;
        expect(nodes).toHaveLength(1);
        expect(nodes[0]?.id).toBe(id);
        expect(nodes[0]?.data.type).toBe("transform_set");
        expect(nodes[0]?.data.label).toBe("Set");
        expect(nodes[0]?.position).toEqual({ x: 10, y: 20 });
    });

    it("добавление помечает граф грязным", () => {
        expect(store().isDirty).toBe(false);
        store().addNodeFromPalette("debug", "Debug", { x: 0, y: 0 });
        expect(store().isDirty).toBe(true);
    });

    it("onNodesChange с remove удаляет узел", () => {
        const id = store().addNodeFromPalette("debug", "Debug", { x: 0, y: 0 });
        store().onNodesChange([{ id, type: "remove" }]);
        expect(store().nodes).toHaveLength(0);
    });

    it("nextNodeId выдаёт разные id", () => {
        const ids = new Set([nextNodeId(), nextNodeId(), nextNodeId()]);
        expect(ids.size).toBe(3);
    });
});

describe("editorStore: параметры узла", () => {
    it("updateNodeParams обновляет только выбранный узел", () => {
        const first = store().addNodeFromPalette("action_http", "HTTP", { x: 0, y: 0 });
        const second = store().addNodeFromPalette("debug", "Debug", { x: 1, y: 1 });

        store().updateNodeParams(first, { url: "https://example.com" });
        const nodes = store().nodes;

        expect(nodes.find((n) => n.id === first)?.data.params).toEqual({
            url: "https://example.com",
        });
        expect(nodes.find((n) => n.id === second)?.data.params).toEqual({});
    });

    it("updateNodeParams сохраняет ранее заданные поля", () => {
        const id = store().addNodeFromPalette("debug", "Debug", { x: 0, y: 0 });
        store().updateNodeParams(id, { message: "hello", level: "info" });
        expect(store().nodes[0]?.data.params).toEqual({ message: "hello", level: "info" });
    });
});

describe("editorStore: рёбра", () => {
    it("onConnect добавляет ребро между узлами", () => {
        const a = store().addNodeFromPalette("trigger_manual", "Manual", { x: 0, y: 0 });
        const b = store().addNodeFromPalette("debug", "Debug", { x: 0, y: 100 });

        store().onConnect({ source: a, target: b, sourceHandle: null, targetHandle: null });

        expect(store().edges).toHaveLength(1);
        expect(store().edges[0]?.source).toBe(a);
        expect(store().edges[0]?.target).toBe(b);
    });

    it("onConnect сохраняет sourceHandle для ветки If", () => {
        const ifNode = store().addNodeFromPalette("logic_if", "If", { x: 0, y: 0 });
        const debug = store().addNodeFromPalette("debug", "Debug", { x: 0, y: 100 });

        store().onConnect({
            source: ifNode,
            target: debug,
            sourceHandle: "true",
            targetHandle: null,
        });

        expect(store().edges[0]?.sourceHandle).toBe("true");
    });

    it("onEdgesChange с remove удаляет ребро", () => {
        const a = store().addNodeFromPalette("trigger_manual", "Manual", { x: 0, y: 0 });
        const b = store().addNodeFromPalette("debug", "Debug", { x: 0, y: 100 });
        store().onConnect({ source: a, target: b, sourceHandle: null, targetHandle: null });
        const edgeId = store().edges[0]?.id ?? "";

        store().onEdgesChange([{ id: edgeId, type: "remove" }]);
        expect(store().edges).toHaveLength(0);
    });
});

describe("editorStore: выбор и dirty-флаг", () => {
    it("setSelectedNode сохраняет и сбрасывает выбор", () => {
        store().setSelectedNode("node_a");
        expect(store().selectedNodeId).toBe("node_a");
        store().setSelectedNode(null);
        expect(store().selectedNodeId).toBeNull();
    });

    it("reset очищает dirty и заполняет канвас из графа", () => {
        store().addNodeFromPalette("debug", "Debug", { x: 0, y: 0 });
        expect(store().isDirty).toBe(true);

        const graph: WorkflowGraph = {
            nodes: [
                {
                    id: "n1",
                    type: "trigger_manual",
                    params: {},
                    position: { x: 5, y: 5 },
                },
            ],
            edges: [],
            layout: {},
        };
        store().reset(graph);

        expect(store().nodes).toHaveLength(1);
        expect(store().nodes[0]?.data.type).toBe("trigger_manual");
        expect(store().isDirty).toBe(false);
    });

    it("markClean сбрасывает флаг", () => {
        store().addNodeFromPalette("debug", "Debug", { x: 0, y: 0 });
        store().markClean();
        expect(store().isDirty).toBe(false);
    });
});

describe("toBackendGraph", () => {
    it("сериализует узлы в проводной формат {id,type,params,position}", () => {
        const id = store().addNodeFromPalette("action_llm", "LLM", { x: 3, y: 4 });
        store().updateNodeParams(id, { prompt: "hi" });

        const graph = toBackendGraph(store().nodes, store().edges);
        const node = graph.nodes[0];

        expect(node).toEqual({
            id,
            type: "action_llm",
            params: { prompt: "hi" },
            position: { x: 3, y: 4 },
        });
        // ключа data быть не должно — бэкенд-схема его не знает
        expect(Object.keys(node ?? {})).not.toContain("data");
    });

    it("преобразует null-хендлы ребра в undefined (как в схеме бэкенда)", () => {
        const edges: Edge[] = [
            {
                id: "e1",
                source: "a",
                target: "b",
                sourceHandle: null,
                targetHandle: null,
            },
        ];
        const graph = toBackendGraph([], edges);
        expect(graph.edges[0]?.sourceHandle).toBeUndefined();
        expect(graph.edges[0]?.targetHandle).toBeUndefined();
    });
});