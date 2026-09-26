import { act, createElement, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// React требует этот флаг, иначе act() ругается «environment is not configured»
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/**
 * Минимальный `renderHook` на React + react-dom (без @testing-library/react,
 * которого в проекте нет). Даёт `result.current` и `rerender`.
 *
 * Оборачивает в QueryClientProvider: хук useExecutionLogs использует useQuery
 * для fallback-polling.
 */

export interface RenderedHook<T> {
    result: { current: T };
    rerender: () => void;
    unmount: () => void;
    container: HTMLDivElement;
}

export function renderHook<T>(hook: () => T): RenderedHook<T> {
    const container = document.createElement("div");
    document.body.appendChild(container);
    const root: Root = createRoot(container);

    const result = { current: undefined as T };
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false } },
    });

    function Wrapper({ children }: { children: ReactNode }) {
        return createElement(QueryClientProvider, { client: queryClient }, children);
    }

    function Probe() {
        result.current = hook();
        return null;
    }

    act(() => {
        root.render(createElement(Wrapper, null, createElement(Probe)));
    });

    return {
        result,
        rerender: () => {
            act(() => {
                root.render(createElement(Wrapper, null, createElement(Probe)));
            });
        },
        unmount: () => {
            act(() => {
                root.unmount();
            });
            container.remove();
            queryClient.clear();
        },
        container,
    };
}

/** Flush микротасок и таймеров: даёт эффектам/промисам «дозреть». */
export async function flush(): Promise<void> {
    await act(async () => {
        await Promise.resolve();
    });
}