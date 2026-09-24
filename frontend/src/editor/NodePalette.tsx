import { useQuery } from "@tanstack/react-query";
import { Bug, GitBranch, Globe, Play, Wand2, type LucideIcon } from "lucide-react";
import type { DragEvent } from "react";

import { type NodeTypeSchema, getNodeTypes } from "@/api/nodeTypes";

const CATEGORY_ICONS: Record<string, LucideIcon> = {
    trigger: Play,
    action: Globe,
    transform: Wand2,
    logic: GitBranch,
    debug: Bug,
};

const CATEGORY_LABELS: Record<string, string> = {
    trigger: "Триггеры",
    action: "Действия",
    transform: "Преобразование",
    logic: "Логика",
    debug: "Отладка",
};

const CATEGORY_ORDER = ["trigger", "action", "transform", "logic", "debug"];

/** Каталог меняется только с релизом бэкенда — держим кэш долго. */
export function useNodeTypes() {
    return useQuery({
        queryKey: ["node-types"],
        queryFn: getNodeTypes,
        staleTime: 60 * 60 * 1000,
    });
}

function onDragStart(event: DragEvent<HTMLDivElement>, nodeType: NodeTypeSchema) {
    event.dataTransfer.setData(
        "application/felagi-node",
        JSON.stringify({ type: nodeType.type, label: nodeType.label }),
    );
    event.dataTransfer.effectAllowed = "move";
}

export function NodePalette() {
    const { data: nodeTypes, isLoading } = useNodeTypes();

    if (isLoading) return <div className="p-4 text-sm text-muted-foreground">Загрузка…</div>;

    const grouped = new Map<string, NodeTypeSchema[]>();
    for (const nodeType of nodeTypes ?? []) {
        const list = grouped.get(nodeType.category) ?? [];
        list.push(nodeType);
        grouped.set(nodeType.category, list);
    }

    return (
        <aside className="w-56 shrink-0 overflow-y-auto border-r bg-card p-3">
            <h2 className="mb-3 text-sm font-semibold">Узлы</h2>
            {CATEGORY_ORDER.filter((category) => grouped.has(category)).map((category) => {
                const Icon = CATEGORY_ICONS[category] ?? Bug;
                return (
                    <div key={category} className="mb-4">
                        <div className="mb-1 text-xs font-medium uppercase text-muted-foreground">
                            {CATEGORY_LABELS[category] ?? category}
                        </div>
                        <div className="flex flex-col gap-1">
                            {(grouped.get(category) ?? []).map((nodeType) => (
                                <div
                                    key={nodeType.type}
                                    draggable
                                    onDragStart={(event) => onDragStart(event, nodeType)}
                                    data-testid={`palette-${nodeType.type}`}
                                    className="flex cursor-grab items-center gap-2 rounded-md border bg-background px-2 py-1.5 text-sm hover:bg-accent"
                                >
                                    <Icon className="h-3.5 w-3.5 text-muted-foreground" />
                                    {nodeType.label}
                                </div>
                            ))}
                        </div>
                    </div>
                );
            })}
        </aside>
    );
}