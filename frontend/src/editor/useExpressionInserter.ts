import { useCallback, useRef, useState } from "react";

/** Копирует текст в буфер обмена; при недоступности (нет API/запрет) - молча. */
export function copyToClipboard(text: string): void {
    void navigator.clipboard?.writeText(text).catch(() => undefined);
}

export interface ExpressionInserter {
    /** Начать вставку в поле `name` (вызывается из onFocus поля). */
    focusField: (name: string) => (element: HTMLInputElement) => void;
    /**
     * Вставить expression: в активное поле (дописав в конец значения), а если
     * фокуса на поле нет - скопировать в буфер обмена (fallback).
     */
    insert: (expression: string) => void;
    /** Имя поля, в которое сейчас придёт вставка (null - фокуса нет). */
    activeField: string | null;
}

/**
 * Трекинг фокуса поля параметра + вставка expression кликом по "доступным
 * данным". Вынесено из ParamsPanel, чтобы тестировать логику вставки без
 * полной отрисовки панели (в проекте нет @testing-library/react).
 *
 * `draft`/`patch` читаются через ref: `insert` всегда использует актуальные
 * значение поля и запись params, даже если хук не пересоздавался.
 */
export function useExpressionInserter(
    draft: Record<string, unknown>,
    patch: (next: Record<string, unknown>) => void,
): ExpressionInserter {
    const focusedField = useRef<HTMLInputElement | null>(null);
    const [activeField, setActiveField] = useState<string | null>(null);

    const draftRef = useRef(draft);
    draftRef.current = draft;
    const patchRef = useRef(patch);
    patchRef.current = patch;
    const activeFieldRef = useRef(activeField);
    activeFieldRef.current = activeField;

    const focusField = useCallback(
        (name: string) => (element: HTMLInputElement) => {
            focusedField.current = element;
            setActiveField(name);
        },
        [],
    );

    const insert = useCallback((expression: string) => {
        const field = focusedField.current;
        const name = activeFieldRef.current;
        if (field && name) {
            const current = draftRef.current[name];
            const text = current === undefined || current === null ? "" : String(current);
            patchRef.current({ ...draftRef.current, [name]: text + expression });
        } else {
            copyToClipboard(expression);
        }
    }, []);

    return { focusField, insert, activeField };
}
