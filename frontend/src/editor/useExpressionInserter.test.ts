import { describe, expect, it, vi } from "vitest";

import { useExpressionInserter } from "@/editor/useExpressionInserter";
import { act } from "react";
import { renderHook } from "@/test-utils/renderHook";

/**
 * Логика вставки expression кликом по «доступным данным»: в активное поле или,
 * если фокуса нет, — в clipboard.
 */

function makeField(): HTMLInputElement {
    return document.createElement("input");
}

describe("useExpressionInserter", () => {
    it("вставляет expression в активное поле (дописывает в конец)", () => {
        let draft: Record<string, unknown> = { text: "Привет, " };
        const patch = vi.fn((next: Record<string, unknown>) => {
            draft = next;
        });
        const { result, unmount } = renderHook(() => useExpressionInserter(draft, patch));

        act(() => {
            result.current.focusField("text")(makeField());
        });
        act(() => {
            result.current.insert("{{ nodes.cron.output }}");
        });

        expect(patch).toHaveBeenCalledTimes(1);
        expect(patch.mock.calls[0]?.[0]).toEqual({
            text: "Привет, {{ nodes.cron.output }}",
        });
        unmount();
    });

    it("вставляет в пустое поле без префикса", () => {
        let draft: Record<string, unknown> = {};
        const patch = vi.fn((next: Record<string, unknown>) => {
            draft = next;
        });
        const { result, unmount } = renderHook(() => useExpressionInserter(draft, patch));

        act(() => result.current.focusField("url")(makeField()));
        act(() => result.current.insert("{{ nodes.a.output }}"));

        expect(patch.mock.calls[0]?.[0]).toEqual({ url: "{{ nodes.a.output }}" });
        unmount();
    });

    it("без фокуса на поле — копирует в clipboard (fallback)", () => {
        const writeText = vi.fn().mockResolvedValue(undefined);
        vi.stubGlobal("navigator", { clipboard: { writeText } });

        const patch = vi.fn();
        const { result, unmount } = renderHook(() => useExpressionInserter({}, patch));

        act(() => result.current.insert("{{ nodes.x.output }}"));

        expect(patch).not.toHaveBeenCalled();
        expect(writeText).toHaveBeenCalledWith("{{ nodes.x.output }}");
        unmount();
        vi.unstubAllGlobals();
    });

    it("activeField отражает последнее сфокусированное поле", () => {
        const { result, unmount } = renderHook(() => useExpressionInserter({}, vi.fn()));

        act(() => result.current.focusField("first")(makeField()));
        expect(result.current.activeField).toBe("first");
        act(() => result.current.focusField("second")(makeField()));
        expect(result.current.activeField).toBe("second");
        unmount();
    });
});