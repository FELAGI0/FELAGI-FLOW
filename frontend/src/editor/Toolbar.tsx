import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface ToolbarProps {
    workflowName: string;
    status: string;
    isDirty: boolean;
    isSaving: boolean;
    isPublishing: boolean;
    onRename: (name: string) => void;
    onSave: () => void;
    onPublish: () => void;
    backTo: string;
}

export function Toolbar({
    workflowName,
    status,
    isDirty,
    isSaving,
    isPublishing,
    onRename,
    onSave,
    onPublish,
    backTo,
}: ToolbarProps) {
    return (
        <header className="flex items-center gap-3 border-b bg-card px-4 py-2">
            <Button variant="ghost" size="sm" asChild>
                <Link to={backTo}>← Назад</Link>
            </Button>

            <Input
                value={workflowName}
                onChange={(event) => onRename(event.target.value)}
                className="max-w-xs"
                aria-label="Имя workflow"
            />

            <span
                className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground"
                data-testid="workflow-status"
            >
                {status}
            </span>
            {isDirty && <span className="text-xs text-amber-600">● не сохранено</span>}

            <div className="ml-auto flex gap-2">
                <Button variant="outline" size="sm" onClick={onSave} disabled={isSaving}>
                    {isSaving ? "Сохранение…" : "Сохранить"}
                </Button>
                <Button size="sm" onClick={onPublish} disabled={isPublishing}>
                    {isPublishing ? "Публикация…" : "Опубликовать"}
                </Button>
            </div>
        </header>
    );
}