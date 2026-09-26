import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface ToolbarProps {
    workflowName: string;
    status: string;
    lastVersion: number | null;
    isDirty: boolean;
    isSaving: boolean;
    isRunning: boolean;
    onRename: (name: string) => void;
    onSave: () => void;
    onRun: () => void;
    onOpenVersions: () => void;
    onOpenPublish: () => void;
    backTo: string;
}

const STATUS_CLASSES: Record<string, string> = {
    draft: "border-slate-300 text-slate-600",
    active: "border-emerald-300 bg-emerald-50 text-emerald-900",
    paused: "border-amber-300 bg-amber-50 text-amber-900",
};

export function Toolbar({
    workflowName,
    status,
    lastVersion,
    isDirty,
    isSaving,
    isRunning,
    onRename,
    onSave,
    onRun,
    onOpenVersions,
    onOpenPublish,
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
                className={`rounded-full border px-2 py-0.5 text-xs ${STATUS_CLASSES[status] ?? ""}`}
                data-testid="workflow-status"
            >
                {status}
            </span>
            {lastVersion !== null && (
                <span className="text-xs text-muted-foreground" data-testid="last-version">
                    v{lastVersion}
                </span>
            )}
            {isDirty && <span className="text-xs text-amber-600">● не сохранено</span>}

            <div className="ml-auto flex gap-2">
                <Button variant="outline" size="sm" onClick={onOpenVersions}>
                    Версии
                </Button>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={onSave}
                    disabled={isSaving}
                    data-testid="save-button"
                >
                    {isSaving ? "Сохранение…" : "Сохранить"}
                </Button>
                <Button
                    variant="outline"
                    size="sm"
                    onClick={onRun}
                    disabled={isRunning}
                    data-testid="run-button"
                >
                    {isRunning ? "Запуск…" : "Запустить"}
                </Button>
                <Button size="sm" onClick={onOpenPublish} data-testid="publish-button">
                    Опубликовать
                </Button>
            </div>
        </header>
    );
}