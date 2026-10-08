import { describe, expect, it } from "vitest";

import { getUpstreamNodes, type UpstreamInput } from "@/editor/graph";

/**
 * Граф Cron -> HTTP -> LLM -> Telegram (цепочка). Проверяем, что для каждого узла
 * возвращаются ровно его предки (по пути edges) в порядке выполнения.
 */
function chain(): UpstreamInput {
    return {
        nodes: [
            { id: "cron", type: "trigger_cron" },
            { id: "http", type: "action_http" },
            { id: "llm", type: "action_llm" },
            { id: "tg", type: "action_telegram" },
        ],
        edges: [
            { source: "cron", target: "http" },
            { source: "http", target: "llm" },
            { source: "llm", target: "tg" },
        ],
    };
}

describe("getUpstreamNodes", () => {
    it("для HTTP — только Cron", () => {
        const result = getUpstreamNodes("http", chain());
        expect(result.map((n) => n.id)).toEqual(["cron"]);
    });

    it("для LLM — Cron и HTTP в порядке выполнения", () => {
        const result = getUpstreamNodes("llm", chain());
        expect(result.map((n) => n.id)).toEqual(["cron", "http"]);
    });

    it("для Telegram — Cron, HTTP, LLM", () => {
        const result = getUpstreamNodes("tg", chain());
        expect(result.map((n) => n.id)).toEqual(["cron", "http", "llm"]);
    });

    it("для первого узла — пусто (нет предков)", () => {
        expect(getUpstreamNodes("cron", chain())).toEqual([]);
    });

    it("возвращает id, type и label (label из узла, иначе type)", () => {
        const graph: UpstreamInput = {
            nodes: [
                { id: "a", type: "trigger_cron", label: "Расписание" },
                { id: "b", type: "debug" },
                { id: "c", type: "action_http" },
            ],
            edges: [
                { source: "a", target: "c" },
                { source: "b", target: "c" },
            ],
        };
        const result = getUpstreamNodes("c", graph);
        expect(result).toEqual([
            { id: "a", type: "trigger_cron", label: "Расписание" },
            { id: "b", type: "debug", label: "debug" },
        ]);
    });

    it("не включает несвязанные узлы", () => {
        const graph: UpstreamInput = {
            nodes: [
                { id: "a", type: "trigger_manual" },
                { id: "b", type: "action_http" },
                { id: "unrelated", type: "debug" },
            ],
            edges: [{ source: "a", target: "b" }],
        };
        // unrelated не имеет пути до b - не должен попасть
        expect(getUpstreamNodes("b", graph).map((n) => n.id)).toEqual(["a"]);
    });

    it("для несуществующего узла — пусто", () => {
        expect(getUpstreamNodes("nope", chain())).toEqual([]);
    });

    it("транзитивность и ветвление: собирает всех предков (diamond)", () => {
        // a -> b, a -> c, b -> d, c -> d
        const graph: UpstreamInput = {
            nodes: [
                { id: "a", type: "trigger_manual" },
                { id: "b", type: "action_http" },
                { id: "c", type: "action_http" },
                { id: "d", type: "debug" },
            ],
            edges: [
                { source: "a", target: "b" },
                { source: "a", target: "c" },
                { source: "b", target: "d" },
                { source: "c", target: "d" },
            ],
        };
        const ids = getUpstreamNodes("d", graph).map((n) => n.id);
        expect(ids).toEqual(["a", "b", "c"]);
    });

    it("цикл не вешает функцию и не дублирует узлы", () => {
        const graph: UpstreamInput = {
            nodes: [
                { id: "a", type: "action_http" },
                { id: "b", type: "action_http" },
            ],
            edges: [
                { source: "a", target: "b" },
                { source: "b", target: "a" },
            ],
        };
        const ids = getUpstreamNodes("b", graph).map((n) => n.id);
        expect(ids).toEqual(["a"]);
        expect(new Set(ids).size).toBe(ids.length);
    });
});
