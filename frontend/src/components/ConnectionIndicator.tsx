import { cn } from "@/lib/utils";
import type { ConnectionState } from "@/hooks/useExecutionLogs";

/** Индикатор состояния live-подписки (5.C.2). Цветные точки + подпись. */
const STATE_META: Record<
    ConnectionState,
    { dot: string; label: string; pulse?: boolean }
> = {
    live: { dot: "bg-emerald-500", label: "Live" },
    connecting: { dot: "bg-amber-400", label: "Подключение…", pulse: true },
    reconnecting: { dot: "bg-orange-500", label: "Переподключение…", pulse: true },
    closed: { dot: "bg-slate-400", label: "Отключено" },
    fallback: { dot: "bg-blue-500", label: "Fallback (polling)" },
};

export function ConnectionIndicator({ state }: { state: ConnectionState }) {
    const meta = STATE_META[state];
    return (
        <span
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground"
            data-testid={`connection-${state}`}
        >
            <span
                className={cn(
                    "h-2 w-2 rounded-full",
                    meta.dot,
                    meta.pulse && "animate-pulse",
                )}
            />
            {meta.label}
        </span>
    );
}