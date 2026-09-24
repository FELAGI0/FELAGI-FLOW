import {
    Background,
    Controls,
    MiniMap,
    ReactFlow,
    type NodeTypes,
    useReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { type DragEvent, useCallback, useMemo } from "react";

import { BaseNode } from "@/editor/nodes/BaseNode";
import { useEditorStore } from "@/stores/editorStore";

const PALETTE_MIME = "application/felagi-node";

/** Узел выбирается по клику — так панель параметров получает контекст. */
export function FlowCanvas() {
    const nodes = useEditorStore((state) => state.nodes);
    const edges = useEditorStore((state) => state.edges);
    const onNodesChange = useEditorStore((state) => state.onNodesChange);
    const onEdgesChange = useEditorStore((state) => state.onEdgesChange);
    const onConnect = useEditorStore((state) => state.onConnect);
    const addNodeFromPalette = useEditorStore((state) => state.addNodeFromPalette);
    const setSelectedNode = useEditorStore((state) => state.setSelectedNode);
    const { screenToFlowPosition } = useReactFlow();

    const nodeTypes = useMemo<NodeTypes>(() => ({ base: BaseNode }), []);

    const onDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
    }, []);

    const onDrop = useCallback(
        (event: DragEvent<HTMLDivElement>) => {
            event.preventDefault();
            const raw = event.dataTransfer.getData(PALETTE_MIME);
            if (!raw) return;
            const { type, label } = JSON.parse(raw) as { type: string; label: string };
            const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
            addNodeFromPalette(type, label, position);
        },
        [addNodeFromPalette, screenToFlowPosition],
    );

    return (
        <div className="h-full w-full" onDrop={onDrop} onDragOver={onDragOver}>
            <ReactFlow
                nodes={nodes}
                edges={edges}
                nodeTypes={nodeTypes}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={onConnect}
                onNodeClick={(_, node) => setSelectedNode(node.id)}
                onPaneClick={() => setSelectedNode(null)}
                fitView
                proOptions={{ hideAttribution: true }}
            >
                <Background />
                <Controls />
                <MiniMap pannable zoomable />
            </ReactFlow>
        </div>
    );
}