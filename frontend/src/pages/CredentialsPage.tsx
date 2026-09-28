import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { createCredential, deleteCredential, listCredentials } from "@/api/credentials";
import type { Credential } from "@/api/credentials";
import { Button } from "@/components/ui/button";
import {
    Dialog,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";

/** Пока поддерживается только Telegram (6.A); список сервисов расширяется позже. */
const SUPPORTED_SERVICES = [{ value: "telegram", label: "Telegram" }] as const;

export function CredentialsPage() {
    const { wsId = "" } = useParams();
    const queryClient = useQueryClient();
    const toast = useToast();

    const [formOpen, setFormOpen] = useState(false);
    const [service, setService] = useState<string>("telegram");
    const [name, setName] = useState("");
    const [token, setToken] = useState("");
    const [pendingDelete, setPendingDelete] = useState<Credential | null>(null);

    const { data: credentials, isLoading } = useQuery({
        queryKey: ["credentials", wsId],
        queryFn: () => listCredentials(wsId),
        enabled: Boolean(wsId),
    });

    const createMutation = useMutation({
        mutationFn: () =>
            createCredential(wsId, { service, name: name.trim(), payload: { token: token.trim() } }),
        onSuccess: async () => {
            await queryClient.invalidateQueries({ queryKey: ["credentials", wsId] });
            setFormOpen(false);
            setName("");
            setToken("");
            toast.show("Credential добавлен", "success");
        },
        onError: (error) =>
            toast.show(error instanceof Error ? error.message : "Не удалось добавить", "error"),
    });

    const deleteMutation = useMutation({
        mutationFn: (credentialId: string) => deleteCredential(wsId, credentialId),
        onSuccess: async () => {
            await queryClient.invalidateQueries({ queryKey: ["credentials", wsId] });
            setPendingDelete(null);
            toast.show("Credential удалён", "success");
        },
        onError: (error) =>
            toast.show(error instanceof Error ? error.message : "Не удалось удалить", "error"),
    });

    const canSubmit = name.trim().length > 0 && token.trim().length > 0;

    return (
        <div className="mx-auto max-w-3xl p-8">
            <div className="mb-6 flex items-center justify-between">
                <div>
                    <Link
                        to={`/workspaces/${wsId}/workflows`}
                        className="text-sm text-muted-foreground hover:underline"
                    >
                        ← Workflows
                    </Link>
                    <h1 className="text-xl font-semibold">Credentials</h1>
                </div>
                <Button size="sm" onClick={() => setFormOpen(true)} data-testid="create-credential">
                    Добавить
                </Button>
            </div>

            <p className="mb-4 text-sm text-muted-foreground">
                Секреты хранятся зашифрованными и никогда не возвращаются через API — видны
                только название и сервис.
            </p>

            {isLoading && <p className="text-sm text-muted-foreground">Загрузка…</p>}

            <ul className="flex flex-col gap-2">
                {(credentials ?? []).map((credential) => (
                    <li
                        key={credential.id}
                        className="flex items-center gap-3 rounded-md border bg-card px-4 py-3"
                        data-testid={`credential-row-${credential.name}`}
                    >
                        <div className="flex min-w-0 flex-1 flex-col">
                            <span className="truncate font-medium">{credential.name}</span>
                            <span className="text-xs text-muted-foreground">
                                {credential.service} · {credential.auth_type}
                            </span>
                        </div>
                        <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => setPendingDelete(credential)}
                            data-testid={`credential-delete-${credential.name}`}
                        >
                            Удалить
                        </Button>
                    </li>
                ))}
                {!isLoading && (credentials ?? []).length === 0 && (
                    <li className="text-sm text-muted-foreground">
                        Пока нет credentials — добавьте первый.
                    </li>
                )}
            </ul>

            <Dialog open={formOpen} onOpenChange={setFormOpen}>
                <DialogContent data-testid="credential-form">
                    <DialogHeader>
                        <DialogTitle>Новый credential</DialogTitle>
                    </DialogHeader>
                    <div className="flex flex-col gap-4">
                        <div className="flex flex-col gap-1.5">
                            <Label htmlFor="cred-service">Service</Label>
                            <select
                                id="cred-service"
                                className="rounded-md border bg-background px-3 py-2 text-sm"
                                value={service}
                                onChange={(event) => setService(event.target.value)}
                                data-testid="credential-service"
                            >
                                {SUPPORTED_SERVICES.map((option) => (
                                    <option key={option.value} value={option.value}>
                                        {option.label}
                                    </option>
                                ))}
                            </select>
                        </div>
                        <div className="flex flex-col gap-1.5">
                            <Label htmlFor="cred-name">Название</Label>
                            <Input
                                id="cred-name"
                                value={name}
                                onChange={(event) => setName(event.target.value)}
                                placeholder="My Telegram bot"
                                data-testid="credential-name"
                            />
                        </div>
                        <div className="flex flex-col gap-1.5">
                            <Label htmlFor="cred-token">Bot token</Label>
                            <Input
                                id="cred-token"
                                type="password"
                                value={token}
                                onChange={(event) => setToken(event.target.value)}
                                placeholder="123456:ABC-DEF…"
                                data-testid="credential-token"
                            />
                            <p className="text-xs text-muted-foreground">
                                Токен получите у @BotFather. Он будет зашифрован и сохранён.
                            </p>
                        </div>
                    </div>
                    <DialogFooter>
                        <Button
                            disabled={!canSubmit || createMutation.isPending}
                            onClick={() => createMutation.mutate()}
                            data-testid="confirm-create-credential"
                        >
                            Сохранить
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <Dialog
                open={pendingDelete !== null}
                onOpenChange={(next) => !next && setPendingDelete(null)}
            >
                <DialogContent data-testid="credential-delete-dialog">
                    <DialogHeader>
                        <DialogTitle>Удалить credential?</DialogTitle>
                    </DialogHeader>
                    <p className="text-sm text-muted-foreground">
                        «{pendingDelete?.name}» перестанет быть доступен узлам. Запуски с ним будут
                        падать с ошибкой «credential deleted».
                    </p>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setPendingDelete(null)}>
                            Отмена
                        </Button>
                        <Button
                            variant="destructive"
                            onClick={() => pendingDelete && deleteMutation.mutate(pendingDelete.id)}
                            disabled={deleteMutation.isPending}
                            data-testid="confirm-delete-credential"
                        >
                            Удалить
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}