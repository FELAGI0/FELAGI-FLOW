import { Handle, Position, type NodeProps } from "@xyflow/react";
import {
    Bug,
    GitBranch,
    Globe,
    Play,
    Sparkles,
    Wand2,
    type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";
import type { EditorNode } from "@/stores/editorStore";

const ICONS: Record<string, LucideIcon> = {
    trigger: Play,
    action: Globe,
    transform: Wand2,
    logic: GitBranch,
    debug: Bug,
    llm: Sparkles,
};

const CATEGORY_COLORS: Record<string, string> = {
    trigger: "bg-emerald-50 border-emerald-300",
    action: "bg-blue-50 border-blue-300",
    transform: "bg-amber-50 border-amber-300",
    logic: "bg-purple-50 border-purple-300",
    debug: "bg-slate-50 border-slate-300",
};

function categoryOf(nodeType: string): string {
    if (nodeType.startsWith("trigger_")) return "trigger";
    if (nodeType.startsWith("action_llm")) return "llm";
    if (nodeType.startsWith("action_")) return "action";
    if (nodeType.startsWith("transform_")) return "transform";
    if (nodeType.startsWith("logic_")) return "logic";
    return "debug";
}

export function BaseNode({ id, data, selected }: NodeProps<EditorNode>) {
    const category = categoryOf(data.type);
    const Icon = ICONS[category] ?? Bug;
    const isIf = data.type === "logic_if";

    return (
        <div
            className={cn(
                "min-w-[160px] rounded-md border-2 px-3 py-2 shadow-sm",
                CATEGORY_COLORS[category] ?? "bg-white border-slate-300",
                selected && "ring-2 ring-ring",
            )}
            data-testid={`node-${id}`}
        >
            <Handle type="target" position={Position.Top} />
            <div className="flex items-center gap-2">
                <Icon className="h-4 w-4 shrink-0 text-slate-600" />
                <div className="flex flex-col">
                    <span className="text-sm font-medium leading-tight">{data.label}</span>
                    <span className="text-[10px] leading-tight text-muted-foreground">
                        {data.type}
                    </span>
                </div>
            </div>

            {isIf ? (
                <>
                    <Handle
                        type="source"
                        position={Position.Bottom}
                        id="true"
                        style={{ left: "30%" }}
                        className="!bg-emerald-500"
                    />
                    <Handle
                        type="source"
                        position={Position.Bottom}
                        id="false"
                        style={{ left: "70%" }}
                        className="!bg-red-500"
                    />
                    <div className="mt-2 flex justify-between text-[10px] text-muted-foreground">
                        <span className="ml-1">true</span>
                        <span className="mr-1">false</span>
                    </div>
                </>
            ) : (
                <Handle type="source" position={Position.Bottom} />
            )}
        </div>
    );
}