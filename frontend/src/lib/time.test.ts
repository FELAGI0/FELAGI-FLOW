import { describe, expect, it } from "vitest";

import { formatDuration, formatRelative, shortId } from "@/lib/time";

const NOW = new Date("2026-09-26T12:00:00Z");

describe("formatRelative", () => {
    it("меньше минуты — «только что»", () => {
        expect(formatRelative(new Date("2026-09-26T11:59:40Z"), NOW)).toBe("только что");
    });

    it("минуты: 1 минута, 2 минуты, 5 минут", () => {
        expect(formatRelative(new Date("2026-09-26T11:59:00Z"), NOW)).toBe("1 минута назад");
        expect(formatRelative(new Date("2026-09-26T11:58:00Z"), NOW)).toBe("2 минуты назад");
        expect(formatRelative(new Date("2026-09-26T11:55:00Z"), NOW)).toBe("5 минут назад");
    });

    it("часы: 2 часа назад", () => {
        expect(formatRelative(new Date("2026-09-26T10:00:00Z"), NOW)).toBe("2 часа назад");
    });

    it("дни: 3 дня назад", () => {
        expect(formatRelative(new Date("2026-09-23T12:00:00Z"), NOW)).toBe("3 дня назад");
    });

    it("будущее — «через …»", () => {
        expect(formatRelative(new Date("2026-09-26T12:05:00Z"), NOW)).toBe("через 5 минут");
    });

    it("принимает ISO-строку", () => {
        expect(formatRelative("2026-09-26T11:00:00Z", NOW)).toBe("1 час назад");
    });

    it("11 часов — «часов» (не «часа»)", () => {
        expect(formatRelative(new Date("2026-09-26T01:00:00Z"), NOW)).toBe("11 часов назад");
    });
});

describe("formatDuration", () => {
    const start = "2026-09-26T12:00:00Z";

    it("меньше минуты — секунды с десятыми", () => {
        expect(formatDuration(start, "2026-09-26T12:00:01.2Z")).toBe("1.2s");
        expect(formatDuration(start, "2026-09-26T12:00:15.4Z")).toBe("15.4s");
    });

    it("минуты и секунды — «2m 3s»", () => {
        expect(formatDuration(start, "2026-09-26T12:02:03Z")).toBe("2m 3s");
    });

    it("ровные минуты — без секунд", () => {
        expect(formatDuration(start, "2026-09-26T12:05:00Z")).toBe("5m");
    });

    it("часы — «1h 2m»", () => {
        expect(formatDuration(start, "2026-09-26T13:02:00Z")).toBe("1h 2m");
    });

    it("незавершённый запуск (нет end) — null", () => {
        expect(formatDuration(start, null)).toBeNull();
    });

    it("нет start — null", () => {
        expect(formatDuration(null, "2026-09-26T12:00:01Z")).toBeNull();
    });
});

describe("shortId", () => {
    it("первые 8 символов", () => {
        expect(shortId("a3443ea5-7218-4bab-9a70-19c218377c66")).toBe("a3443ea5");
    });

    it("короткий id не меняется", () => {
        expect(shortId("abc")).toBe("abc");
    });
});