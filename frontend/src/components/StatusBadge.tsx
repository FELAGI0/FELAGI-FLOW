import { Badge, type BadgeProps } from "@/components/ui/badge";

/** Цвет статуса запуска/шага (5.C.1): queued — серый, running — синий и т.д. */
const STATUS_VARIANT: Record<string, NonNullable<BadgeProps["variant"]>> = {
    queued: "gray",
    running: "blue",
    succeeded: "green",
    failed: "red",
    dead: "darkred",
    canceled: "orange",
    // статус шага, которого нет у запуска
    skipped: "gray",
};

export function StatusBadge({ status }: { status: string }) {
    const variant = STATUS_VARIANT[status] ?? "outline";
    return (
        <Badge variant={variant} data-testid={`status-${status}`}>
            {status}
        </Badge>
    );
}