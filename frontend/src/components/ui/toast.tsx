import { X } from "lucide-react";
import {
    type ReactNode,
    createContext,
    useCallback,
    useContext,
    useEffect,
    useMemo,
    useRef,
    useState,
} from "react";

import { cn } from "@/lib/utils";

export type ToastVariant = "success" | "error" | "info";

interface Toast {
    id: number;
    message: string;
    variant: ToastVariant;
}

interface ToastApi {
    show: (message: string, variant?: ToastVariant) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

const AUTO_HIDE_MS = 4000;
const MAX_TOASTS = 3;

const VARIANT_CLASSES: Record<ToastVariant, string> = {
    success: "border-emerald-300 bg-emerald-50 text-emerald-900",
    error: "border-red-300 bg-red-50 text-red-900",
    info: "border-slate-300 bg-card text-foreground",
};

export function ToastProvider({ children }: { children: ReactNode }) {
    const [toasts, setToasts] = useState<Toast[]>([]);
    const nextId = useRef(0);
    const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>());

    const dismiss = useCallback((id: number) => {
        setToasts((current) => current.filter((toast) => toast.id !== id));
        const timer = timers.current.get(id);
        if (timer) {
            clearTimeout(timer);
            timers.current.delete(id);
        }
    }, []);

    const show = useCallback(
        (message: string, variant: ToastVariant = "info") => {
            const id = nextId.current++;
            // наивный стек: держим не больше MAX_TOASTS, самые старые уходят
            setToasts((current) => [...current, { id, message, variant }].slice(-MAX_TOASTS));
            timers.current.set(
                id,
                setTimeout(() => dismiss(id), AUTO_HIDE_MS),
            );
        },
        [dismiss],
    );

    // сброс таймеров при размонтировании провайдера
    useEffect(() => {
        const currentTimers = timers.current;
        return () => {
            for (const timer of currentTimers.values()) clearTimeout(timer);
        };
    }, []);

    const api = useMemo<ToastApi>(() => ({ show }), [show]);

    return (
        <ToastContext.Provider value={api}>
            {children}
            <div
                className="pointer-events-none fixed bottom-4 right-4 z-[100] flex flex-col gap-2"
                data-testid="toaster"
            >
                {toasts.map((toast) => (
                    <div
                        key={toast.id}
                        data-testid={`toast-${toast.variant}`}
                        role="status"
                        className={cn(
                            "pointer-events-auto flex min-w-[220px] items-start gap-2 rounded-md border px-3 py-2 text-sm shadow-md",
                            VARIANT_CLASSES[toast.variant],
                        )}
                    >
                        <span className="flex-1">{toast.message}</span>
                        <button
                            type="button"
                            onClick={() => dismiss(toast.id)}
                            aria-label="Закрыть"
                            className="opacity-60 hover:opacity-100"
                        >
                            <X className="h-3.5 w-3.5" />
                        </button>
                    </div>
                ))}
            </div>
        </ToastContext.Provider>
    );
}

export function useToast(): ToastApi {
    const context = useContext(ToastContext);
    if (!context) throw new Error("useToast must be used within ToastProvider");
    return context;
}