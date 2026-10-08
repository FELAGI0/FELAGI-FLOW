import { useQuery } from "@tanstack/react-query";
import { Copy } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { listCredentials } from "@/api/credentials";
import type { JsonSchemaProperty, NodeTypeSchema } from "@/api/nodeTypes";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { getUpstreamNodes } from "@/editor/graph";
import { useNodeTypes } from "@/editor/NodePalette";
import { copyToClipboard, useExpressionInserter } from "@/editor/useExpressionInserter";
import { useEditorStore } from "@/stores/editorStore";

/** Опциональность: в JSON-Schema Pydantic приходит как anyOf: [T, {"type":"null"}]. */
function isOptional(prop: JsonSchemaProperty): boolean {
    return Boolean(prop.anyOf?.some((variant) => variant.type === "null"));
}

/** В JSON-Schema из Pydantic опциональный тип приходит как anyOf: [T, {"type":"null"}]. */
function baseProperty(prop: JsonSchemaProperty): JsonSchemaProperty {
    if (prop.anyOf) {
        const nonNull = prop.anyOf.find((variant) => variant.type !== "null");
        if (nonNull) return nonNull;
    }
    return prop;
}

/**
 * Выбор credential для узлов с секретами (action_telegram). Список - из
 * GET /api/workspaces/{ws}/credentials; секрет наружу не отдаётся, только имя.
 * Если credentials нет - ссылка "Добавить" на страницу управления.
 */
function CredentialField({
    value,
    required,
    onChange,
}: {
    value: unknown;
    required: boolean;
    onChange: (value: unknown) => void;
}) {
    const { wsId = "" } = useParams();
    const { data: credentials, isLoading } = useQuery({
        queryKey: ["credentials", wsId],
        queryFn: () => listCredentials(wsId),
        enabled: Boolean(wsId),
    });

    const list = credentials ?? [];

    return (
        <div className="flex flex-col gap-1.5">
            <Label htmlFor="param-credential_id">
                Credential
                {required && <span className="text-destructive"> *</span>}
            </Label>
            {list.length === 0 && !isLoading ? (
                <p className="text-xs text-muted-foreground">
                    Нет credentials.{" "}
                    <Link
                        to={`/workspaces/${wsId}/credentials`}
                        className="text-primary hover:underline"
                        data-testid="credentials-add-link"
                    >
                        Добавить
                    </Link>
                </p>
            ) : (
                <Select
                    value={value === undefined || value === null ? "" : String(value)}
                    onValueChange={(next) => onChange(next)}
                >
                    <SelectTrigger id="param-credential_id" data-testid="param-credential_id">
                        <SelectValue placeholder={isLoading ? "Загрузка…" : "Выберите…"} />
                    </SelectTrigger>
                    <SelectContent>
                        {list.map((credential) => (
                            <SelectItem key={credential.id} value={credential.id}>
                                {credential.name} ({credential.service})
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            )}
        </div>
    );
}

interface FieldProps {
    name: string;
    prop: JsonSchemaProperty;
    required: boolean;
    value: unknown;
    onChange: (value: unknown) => void;
    /** Уведомляет панель, что это поле в фокусе - для вставки expression кликом. */
    onFocus?: (element: HTMLInputElement) => void;
}

function Field({ name, prop, required, value, onChange, onFocus }: FieldProps) {
    const base = baseProperty(prop);
    const label = prop.title ?? name;
    const fieldId = `param-${name}`;

    if (base.enum) {
        return (
            <div className="flex flex-col gap-1.5">
                <Label htmlFor={fieldId}>
                    {label}
                    {required && <span className="text-destructive"> *</span>}
                </Label>
                <Select
                    value={String(value ?? base.default ?? "")}
                    onValueChange={(next) => onChange(next)}
                >
                    <SelectTrigger id={fieldId} data-testid={fieldId}>
                        <SelectValue placeholder="Выберите…" />
                    </SelectTrigger>
                    <SelectContent>
                        {base.enum.map((option) => (
                            <SelectItem key={String(option)} value={String(option)}>
                                {String(option)}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            </div>
        );
    }

    if (base.type === "boolean") {
        return (
            <div className="flex items-center gap-2">
                <input
                    id={fieldId}
                    type="checkbox"
                    checked={Boolean(value ?? base.default ?? false)}
                    onChange={(event) => onChange(event.target.checked)}
                    className="h-4 w-4 rounded border"
                />
                <Label htmlFor={fieldId}>{label}</Label>
            </div>
        );
    }

    const numeric = base.type === "integer" || base.type === "number";

    return (
        <div className="flex flex-col gap-1.5">
            <Label htmlFor={fieldId}>
                {label}
                {required && <span className="text-destructive"> *</span>}
            </Label>
            <Input
                id={fieldId}
                data-testid={fieldId}
                type={numeric ? "number" : "text"}
                step={base.type === "number" ? "any" : undefined}
                value={value === undefined || value === null ? "" : String(value)}
                onFocus={onFocus ? (event) => onFocus(event.currentTarget) : undefined}
                onChange={(event) => {
                    const raw = event.target.value;
                    if (numeric) {
                        onChange(raw === "" ? undefined : Number(raw));
                    } else {
                        onChange(raw);
                    }
                }}
                placeholder={isOptional(prop) ? "необязательно" : ""}
            />
            {prop.description && (
                <p className="text-xs text-muted-foreground">{prop.description}</p>
            )}
        </div>
    );
}

/** Общие параметры всех узлов: рендерятся отдельной секцией, а не через схему. */
const COMMON_PARAMS = ["retry", "label"];

/** Дефолты retry совпадают с backend RetryConfig (node_schemas.py). */
const RETRY_DEFAULTS = {
    max_retries: 0,
    backoff: "exponential",
    base_s: 1.0,
} as const;

/** Варианты backoff - те же, что в pydantic Literal["fixed", "exponential"]. */
type Backoff = "fixed" | "exponential";

interface RetrySectionProps {
    params: Record<string, unknown>;
    onPatch: (patch: Record<string, unknown>) => void;
}

/**
 * Секция Retry + label: общая для всех типов узлов.
 * Значения лежат в тех же params, что уходят на бэкенд (node.params.retry / .label).
 * Пока пользователь не изменил поле, в params ничего не пишется - вместо
 * отсутствующего retry показываются дефолты.
 */
function RetrySection({ params, onPatch }: RetrySectionProps) {
    const stored = (params.retry ?? {}) as Partial<Record<keyof typeof RETRY_DEFAULTS, unknown>>;

    const maxRetries =
        typeof stored.max_retries === "number" ? stored.max_retries : RETRY_DEFAULTS.max_retries;
    const backoff: Backoff =
        stored.backoff === "fixed" || stored.backoff === "exponential"
            ? stored.backoff
            : RETRY_DEFAULTS.backoff;
    const baseS = typeof stored.base_s === "number" ? stored.base_s : RETRY_DEFAULTS.base_s;
    const label = typeof params.label === "string" ? params.label : "";

    function patchRetry(next: Partial<{ max_retries: number; backoff: Backoff; base_s: number }>) {
        onPatch({ retry: { max_retries: maxRetries, backoff, base_s: baseS, ...next } });
    }

    /** Пустое поле возвращается к дефолту - иначе в params ушёл бы NaN. */
    function numberOrDefault(raw: string, fallback: number): number {
        if (raw === "") return fallback;
        const parsed = Number(raw);
        return Number.isFinite(parsed) ? parsed : fallback;
    }

    return (
        <section className="flex flex-col gap-4 border-t pt-4" data-testid="retry-section">
            <h3 className="text-xs font-semibold uppercase text-muted-foreground">Retry</h3>

            <div className="flex flex-col gap-1.5">
                <Label htmlFor="param-max_retries">Max retries</Label>
                <Input
                    id="param-max_retries"
                    data-testid="param-max_retries"
                    type="number"
                    min={0}
                    max={5}
                    step={1}
                    value={String(maxRetries)}
                    onChange={(event) =>
                        patchRetry({
                            max_retries: numberOrDefault(
                                event.target.value,
                                RETRY_DEFAULTS.max_retries,
                            ),
                        })
                    }
                />
                <p className="text-xs text-muted-foreground">
                    Сколько раз повторить узел при ошибке (0–5).
                </p>
            </div>

            <div className="flex flex-col gap-1.5">
                <Label htmlFor="param-backoff">Backoff</Label>
                <Select value={backoff} onValueChange={(next) => patchRetry({ backoff: next as Backoff })}>
                    <SelectTrigger id="param-backoff" data-testid="param-backoff">
                        <SelectValue placeholder="Выберите…" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="exponential">exponential</SelectItem>
                        <SelectItem value="fixed">fixed</SelectItem>
                    </SelectContent>
                </Select>
            </div>

            <div className="flex flex-col gap-1.5">
                <Label htmlFor="param-base_s">Base delay, s</Label>
                <Input
                    id="param-base_s"
                    data-testid="param-base_s"
                    type="number"
                    min={0.1}
                    max={60}
                    step="any"
                    value={String(baseS)}
                    onChange={(event) =>
                        patchRetry({ base_s: numberOrDefault(event.target.value, RETRY_DEFAULTS.base_s) })
                    }
                />
            </div>

            <div className="flex flex-col gap-1.5">
                <Label htmlFor="param-label">Label</Label>
                <Input
                    id="param-label"
                    data-testid="param-label"
                    type="text"
                    value={label}
                    onChange={(event) => onPatch({ label: event.target.value })}
                    placeholder="имя на канвасе"
                />
            </div>
        </section>
    );
}

export function ParamsPanel() {
    const selectedNodeId = useEditorStore((state) => state.selectedNodeId);
    const nodes = useEditorStore((state) => state.nodes);
    const edges = useEditorStore((state) => state.edges);
    const updateNodeParams = useEditorStore((state) => state.updateNodeParams);
    const { data: nodeTypes } = useNodeTypes();

    const node = nodes.find((candidate) => candidate.id === selectedNodeId) ?? null;
    const schema: NodeTypeSchema | undefined = nodeTypes?.find(
        (candidate) => candidate.type === node?.data.type,
    );

    const properties = useMemo(() => {
        const all = schema?.params_schema.properties ?? {};
        // retry/label рендерит RetrySection - иначе они дублировались бы как
        // поля схемы (retry приходит объектом и не рисуется текстовым input'ом)
        return Object.fromEntries(
            Object.entries(all).filter(([name]) => !COMMON_PARAMS.includes(name)),
        );
    }, [schema]);
    const required = useMemo(
        () => new Set(schema?.params_schema.required ?? []),
        [schema],
    );

    const [draft, setDraft] = useState<Record<string, unknown>>({});

    /** Общая запись params: обновляет draft и узел в сторе. */
    function patchParams(next: Record<string, unknown>) {
        if (!node) return;
        setDraft(next);
        updateNodeParams(node.id, next);
    }

    // вставка expression кликом по "доступным данным": в активное поле или clipboard
    const { focusField, insert } = useExpressionInserter(draft, patchParams);

    const upstreamNodes = useMemo(
        () =>
            node
                ? getUpstreamNodes(node.id, {
                      nodes: nodes.map((candidate) => ({
                          id: candidate.id,
                          type: candidate.data.type,
                          label: candidate.data.label,
                      })),
                      edges: edges.map((edge) => ({ source: edge.source, target: edge.target })),
                  })
                : [],
        [node, nodes, edges],
    );

    // при смене узла подтягиваем его параметры и дефолты схемы
    useEffect(() => {
        if (!node) {
            setDraft({});
            return;
        }
        const initial: Record<string, unknown> = {};
        // retry/label не входят в properties (их рисует RetrySection), поэтому
        // переносим их из узла напрямую - иначе первое же изменение param'а
        // в секции Retry затирало бы ранее сохранённые retry/label
        for (const name of COMMON_PARAMS) {
            if (node.data.params[name] !== undefined) {
                initial[name] = node.data.params[name];
            }
        }
        for (const [name, prop] of Object.entries(properties)) {
            const stored = node.data.params[name];
            initial[name] = stored ?? prop.default;
        }
        setDraft(initial);
    }, [node, properties]);

    if (!node) {
        return (
            <aside className="w-72 shrink-0 border-l bg-card p-4">
                <p className="text-sm text-muted-foreground">
                    Выберите узел на канвасе, чтобы настроить параметры.
                </p>
            </aside>
        );
    }

    return (
        <aside className="w-72 shrink-0 overflow-y-auto border-l bg-card p-4">
            <div className="mb-4">
                <h2 className="text-sm font-semibold">{node.data.label}</h2>
                <span className="text-xs text-muted-foreground">{node.data.type}</span>
            </div>

            <div className="mb-4 flex items-center gap-1">
                <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
                    id: <code data-testid="node-id">{node.id}</code>
                </span>
                <Button
                    size="icon"
                    variant="ghost"
                    className="h-6 w-6"
                    title="Скопировать id"
                    aria-label="Скопировать id"
                    data-testid="copy-node-id"
                    onClick={() => copyToClipboard(node.id)}
                >
                    <Copy className="h-3.5 w-3.5" />
                </Button>
            </div>

            {upstreamNodes.length > 0 && (
                <details className="mb-4" data-testid="upstream-details">
                    <summary className="cursor-pointer text-xs font-medium">
                        Доступные данные из предыдущих узлов
                    </summary>
                    <ul className="mt-2 flex flex-col gap-1">
                        {upstreamNodes.map((upstream) => {
                            const expression = `{{ nodes.${upstream.id}.output }}`;
                            return (
                                <li key={upstream.id}>
                                    <button
                                        type="button"
                                        className="w-full rounded px-1 py-0.5 text-left hover:bg-accent"
                                        title="Вставить в поле параметра"
                                        data-testid={`insert-${upstream.id}`}
                                        onClick={() => insert(expression)}
                                    >
                                        <code className="block truncate text-xs text-primary">
                                            {expression}
                                        </code>
                                        <span className="text-xs text-muted-foreground">
                                            {upstream.label} ({upstream.type})
                                        </span>
                                    </button>
                                </li>
                            );
                        })}
                    </ul>
                </details>
            )}

            {Object.keys(properties).length === 0 ? (
                <p className="text-sm text-muted-foreground">У этого узла нет параметров.</p>
            ) : (
                <div className="flex flex-col gap-4">
                    {Object.entries(properties).map(([name, prop]) =>
                        name === "credential_id" ? (
                            <CredentialField
                                key={name}
                                value={draft[name]}
                                required={required.has(name)}
                                onChange={(value) => patchParams({ ...draft, [name]: value })}
                            />
                        ) : (
                            <Field
                                key={name}
                                name={name}
                                prop={prop}
                                required={required.has(name)}
                                value={draft[name]}
                                onFocus={focusField(name)}
                                onChange={(value) => patchParams({ ...draft, [name]: value })}
                            />
                        ),
                    )}
                </div>
            )}

            <RetrySection
                params={draft}
                onPatch={(patch) => patchParams({ ...draft, ...patch })}
            />
        </aside>
    );
}
