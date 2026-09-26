import { type VariantProps, cva } from "class-variance-authority";
import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
    "inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium",
    {
        variants: {
            variant: {
                default: "border-transparent bg-primary text-primary-foreground",
                outline: "border-border text-foreground",
                // серый — нейтральное/ожидание
                gray: "border-slate-300 bg-slate-50 text-slate-700",
                // синий — выполняется
                blue: "border-blue-300 bg-blue-50 text-blue-900",
                // зелёный — успех
                green: "border-emerald-300 bg-emerald-50 text-emerald-900",
                // красный — ошибка
                red: "border-red-300 bg-red-50 text-red-900",
                // тёмно-красный — dead (исчерпаны попытки)
                darkred: "border-red-800 bg-red-800 text-white",
                // оранжевый — отменено
                orange: "border-orange-300 bg-orange-50 text-orange-900",
                // янтарный — предупреждение/пауза
                amber: "border-amber-300 bg-amber-50 text-amber-900",
            },
        },
        defaultVariants: { variant: "default" },
    },
);

export interface BadgeProps
    extends HTMLAttributes<HTMLSpanElement>,
        VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
    return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { badgeVariants };