/**
 * Операции над графом воркфлоу для редактора (без зависимости от React).
 *
 * Сейчас здесь только `getUpstreamNodes`: какие узлы реально идут РАНЬШЕ
 * текущего (есть путь по edges до него). Это нужно панели параметров, чтобы
 * показать пользователю доступные expressions `{{ nodes.<id>.output... }}` —
 * иначе id узла не виден, и выражение не составить.
 */

/** Узел, доступный для ссылки из текущего узла. */
export interface UpstreamNode {
    id: string;
    type: string;
    label: string;
}

/** Минимальная форма графа, которую читает getUpstreamNodes (не завязана на React Flow). */
export interface UpstreamInput {
    nodes: readonly { id: string; type: string; label?: string }[];
    edges: readonly { source: string; target: string }[];
}

/** Множество предков nodeId: узлы, из которых есть путь по edges до nodeId. */
function ancestorsOf(nodeId: string, edges: UpstreamInput["edges"]): Set<string> {
    // обратные рёбра: target → [источники]
    const incoming = new Map<string, string[]>();
    for (const edge of edges) {
        const list = incoming.get(edge.target);
        if (list) list.push(edge.source);
        else incoming.set(edge.target, [edge.source]);
    }

    const ancestors = new Set<string>();
    const stack = [...(incoming.get(nodeId) ?? [])];
    while (stack.length > 0) {
        const current = stack.pop() as string;
        if (ancestors.has(current)) continue;
        ancestors.add(current);
        for (const parent of incoming.get(current) ?? []) stack.push(parent);
    }
    // узел не является своим предком, даже если в графе цикл до него
    ancestors.delete(nodeId);
    return ancestors;
}

/**
 * Топологический порядок (Kahn). Детерминированный: среди узлов с нулевой
 * входящей степенью первыми идут триггеры (как в backend runner), затем по id.
 * При цикле возвращает исходный порядок узлов (граф всё равно невалиден).
 */
function topologicalIds(input: UpstreamInput): string[] {
    const ids = input.nodes.map((node) => node.id);
    const typeById = new Map(input.nodes.map((node) => [node.id, node.type]));
    const indegree = new Map<string, number>(ids.map((id) => [id, 0]));
    const adjacency = new Map<string, string[]>();

    for (const edge of input.edges) {
        if (!indegree.has(edge.source) || !indegree.has(edge.target)) continue;
        indegree.set(edge.target, (indegree.get(edge.target) ?? 0) + 1);
        const list = adjacency.get(edge.source);
        if (list) list.push(edge.target);
        else adjacency.set(edge.source, [edge.target]);
    }

    const roots = ids
        .filter((id) => indegree.get(id) === 0)
        .sort((a, b) => {
            const aTrigger = typeById.get(a)?.startsWith("trigger_") ? 0 : 1;
            const bTrigger = typeById.get(b)?.startsWith("trigger_") ? 0 : 1;
            return aTrigger - bTrigger || (a < b ? -1 : a > b ? 1 : 0);
        });

    const queue = [...roots];
    const order: string[] = [];
    while (queue.length > 0) {
        const current = queue.shift() as string;
        order.push(current);
        for (const neighbour of adjacency.get(current) ?? []) {
            const next = (indegree.get(neighbour) ?? 0) - 1;
            indegree.set(neighbour, next);
            if (next === 0) queue.push(neighbour);
        }
    }

    return order.length === ids.length ? order : ids;
}

/**
 * Узлы, из которых есть путь до nodeId, в порядке выполнения (topological).
 * `label` берётся из узла, при отсутствии — из type. Если узла нет в графе —
 * пустой массив.
 */
export function getUpstreamNodes(nodeId: string, input: UpstreamInput): UpstreamNode[] {
    if (!input.nodes.some((node) => node.id === nodeId)) return [];

    const ancestors = ancestorsOf(nodeId, input.edges);
    const byId = new Map(input.nodes.map((node) => [node.id, node]));

    const result: UpstreamNode[] = [];
    for (const id of topologicalIds(input)) {
        if (!ancestors.has(id)) continue;
        const node = byId.get(id);
        if (!node) continue;
        result.push({ id: node.id, type: node.type, label: node.label ?? node.type });
    }
    return result;
}