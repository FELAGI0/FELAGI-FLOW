import { useState } from "react";

import { cn } from "@/lib/utils";

/** Разворачиваемый JSON-блок: заголовок-кнопка + pretty-printed тело. */
export function JsonViewer({
    label,
    value,
    defaultOpen = false,
    testId,
}: {
    label: string;
    value: unknown;
    defaultOpen?: boolean;
    testId?: string;
}) {
    const [open, setOpen] = useState(defaultOpen);
    const text = JSON.stringify(value, null, 2) ?? "null";

    return (
        <div className="rounded-md border bg-muted/30" data-testid={testId}>
            <button
                type="button"
                onClick={() => setOpen((current) => !current)}
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs font-medium"
            >
                <span className="text-muted-foreground">{open ? "▾" : "▸"}</span>
                {label}
            </button>
            {open && (
                <pre
                    className={cn(
                        "max-h-80 overflow-auto border-t px-3 py-2 font-mono text-xs",
                    )}
                >
                    {text}
                </pre>
            )}
        </div>
    );
}