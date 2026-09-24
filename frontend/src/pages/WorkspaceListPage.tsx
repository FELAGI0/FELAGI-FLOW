import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { listWorkspaces } from "@/api/workspaces";
import { Button } from "@/components/ui/button";
import { logout } from "@/api/client";
import { useNavigate } from "react-router-dom";

export function WorkspaceListPage() {
    const navigate = useNavigate();
    const { data: workspaces, isLoading, error } = useQuery({
        queryKey: ["workspaces"],
        queryFn: listWorkspaces,
    });

    async function onLogout() {
        await logout();
        navigate("/login");
    }

    return (
        <div className="mx-auto max-w-3xl p-8">
            <div className="mb-6 flex items-center justify-between">
                <h1 className="text-xl font-semibold">Workspace&apos;ы</h1>
                <Button variant="outline" size="sm" onClick={onLogout}>
                    Выйти
                </Button>
            </div>

            {isLoading && <p className="text-sm text-muted-foreground">Загрузка…</p>}
            {error && <p className="text-sm text-destructive">{error.message}</p>}

            <ul className="flex flex-col gap-2">
                {(workspaces ?? []).map((workspace) => (
                    <li key={workspace.id}>
                        <Link
                            to={`/workspaces/${workspace.id}/workflows`}
                            className="flex items-center justify-between rounded-md border bg-card px-4 py-3 hover:bg-accent"
                        >
                            <span className="font-medium">{workspace.name}</span>
                            <span className="text-xs text-muted-foreground">
                                {workspace.current_user_role} · {workspace.plan}
                            </span>
                        </Link>
                    </li>
                ))}
            </ul>
        </div>
    );
}