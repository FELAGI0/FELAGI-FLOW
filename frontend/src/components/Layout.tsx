import { Monitor, Moon, Sun, type LucideIcon } from "lucide-react";
import { Link, Outlet } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { type Theme, nextTheme, useThemeStore } from "@/stores/themeStore";

/** Иконка и подпись текущего режима темы. */
const THEME_META: Record<Theme, { icon: LucideIcon; label: string }> = {
    light: { icon: Sun, label: "Светлая тема" },
    dark: { icon: Moon, label: "Тёмная тема" },
    system: { icon: Monitor, label: "Как в системе" },
};

/**
 * Кнопка-переключатель темы (UI.1). Клик - циклически
 * light -> dark -> system -> light. Применение к <html> делает useTheme,
 * смонтированный один раз в App.
 */
export function ThemeToggle() {
    const theme = useThemeStore((state) => state.theme);
    const setTheme = useThemeStore((state) => state.setTheme);
    const { icon: Icon, label } = THEME_META[theme];

    return (
        <Button
            variant="ghost"
            size="icon"
            onClick={() => setTheme(nextTheme(theme))}
            aria-label={label}
            title={label}
            data-testid="theme-toggle"
        >
            <Icon className="h-4 w-4" />
        </Button>
    );
}

/**
 * Общий каркас аутентифицированных экранов: шапка с брендом и переключателем
 * темы + область страницы. Редактор (EditorPage) сюда не входит - у него
 * собственный полноэкранный Toolbar.
 */
export function Layout() {
    return (
        <div className="flex min-h-screen flex-col bg-background text-foreground">
            <header className="flex items-center gap-3 border-b bg-card px-4 py-2">
                <Link to="/workspaces" className="text-sm font-semibold">
                    Felagi Flow
                </Link>
                <div className="ml-auto flex items-center">
                    <ThemeToggle />
                </div>
            </header>
            <main className="flex-1">
                <Outlet />
            </main>
        </div>
    );
}
