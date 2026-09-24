import { describe, expect, it } from "vitest";

import { cn } from "@/lib/utils";

describe("cn", () => {
    it("объединяет классы", () => {
        expect(cn("a", "b")).toBe("a b");
    });

    it("отбрасывает falsy-значения", () => {
        expect(cn("a", false, undefined, null, "b")).toBe("a b");
    });

    it("разрешает конфликт tailwind-классов в пользу последнего", () => {
        expect(cn("p-2", "p-4")).toBe("p-4");
    });

    it("поддерживает условные объекты", () => {
        expect(cn("base", { active: true, disabled: false })).toBe("base active");
    });
});