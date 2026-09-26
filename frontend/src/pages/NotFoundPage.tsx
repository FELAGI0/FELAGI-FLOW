import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";

/** Заглушка 404: недоступные пока маршруты (например, Replay до 7.C). */
export function NotFoundPage() {
    return (
        <div className="mx-auto max-w-md p-8 text-center">
            <h1 className="mb-2 text-2xl font-semibold">404</h1>
            <p className="mb-6 text-sm text-muted-foreground">
                Страница не найдена или ещё не реализована.
            </p>
            <Button variant="outline" size="sm" asChild>
                <Link to="/workspaces">К workspace&apos;ам</Link>
            </Button>
        </div>
    );
}