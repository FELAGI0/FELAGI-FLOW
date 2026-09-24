import { useEffect, useMemo, useState } from "react";

import type { JsonSchemaProperty, NodeTypeSchema } from "@/api/nodeTypes";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useNodeTypes } from "@/editor/NodePalette";
import { useEditorStore } from "@/stores/editorStore";

/** В JSON-Schema из Pydantic опциональный тип приходит как anyOf: [T, {"type":"null"}]. */
function baseProperty(prop: JsonSchemaProperty): JsonSchemaProperty {
    if (prop.anyOf) {
        const nonNull = prop.anyOf.find((variant) => variant.type !== "null");
        if (nonNull) return nonNull;
    }
    return prop;
}

function isOptional(prop: JsonSchemaProperty): boolean {
    return Boolean(prop.anyOf?.some((variant) => variant.type === "null"));
}

interface FieldProps {
    name: string;
    prop: JsonSchemaProperty;
    required: boolean;
    value: unknown;
    onChange: (value: unknown) => void;
}

function Field({ name, prop, required, value, onChange }: FieldProps) {
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

export function ParamsPanel() {
    const selectedNodeId = useEditorStore((state) => state.selectedNodeId);
    const nodes = useEditorStore((state) => state.nodes);
    const updateNodeParams = useEditorStore((state) => state.updateNodeParams);
    const { data: nodeTypes } = useNodeTypes();

    const node = nodes.find((candidate) => candidate.id === selectedNodeId) ?? null;
    const schema: NodeTypeSchema | undefined = nodeTypes?.find(
        (candidate) => candidate.type === node?.data.type,
    );

    const properties = useMemo(
        () => schema?.params_schema.properties ?? {},
        [schema],
    );
    const required = useMemo(
        () => new Set(schema?.params_schema.required ?? []),
        [schema],
    );

    const [draft, setDraft] = useState<Record<string, unknown>>({});

    // при смене узла подтягиваем его параметры и дефолты схемы
    useEffect(() => {
        if (!node) {
            setDraft({});
            return;
        }
        const initial: Record<string, unknown> = {};
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

            {Object.keys(properties).length === 0 ? (
                <p className="text-sm text-muted-foreground">У этого узла нет параметров.</p>
            ) : (
                <div className="flex flex-col gap-4">
                    {Object.entries(properties).map(([name, prop]) => (
                        <Field
                            key={name}
                            name={name}
                            prop={prop}
                            required={required.has(name)}
                            value={draft[name]}
                            onChange={(value) => {
                                const next = { ...draft, [name]: value };
                                setDraft(next);
                                updateNodeParams(node.id, next);
                            }}
                        />
                    ))}
                </div>
            )}
        </aside>
    );
}