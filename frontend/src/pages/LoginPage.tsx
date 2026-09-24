import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";

import { login } from "@/api/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuthStore } from "@/stores/authStore";

export function LoginPage() {
    const navigate = useNavigate();
    const setAccessToken = useAuthStore((state) => state.setAccessToken);
    const [email, setEmail] = useState("");
    const [password, setPassword] = useState("");
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);

    async function onSubmit(event: FormEvent) {
        event.preventDefault();
        setError(null);
        setBusy(true);
        try {
            const result = await login(email, password);
            setAccessToken(result.access_token);
            navigate("/workspaces");
        } catch (err) {
            setError(err instanceof Error ? err.message : "Не удалось войти");
        } finally {
            setBusy(false);
        }
    }

    return (
        <div className="flex min-h-screen items-center justify-center bg-muted/40">
            <form
                onSubmit={onSubmit}
                className="w-full max-w-sm rounded-lg border bg-card p-6 shadow-sm"
            >
                <h1 className="mb-1 text-lg font-semibold">Felagi Flow</h1>
                <p className="mb-4 text-sm text-muted-foreground">Вход в аккаунт</p>

                <div className="flex flex-col gap-3">
                    <div className="flex flex-col gap-1.5">
                        <Label htmlFor="email">Email</Label>
                        <Input
                            id="email"
                            type="email"
                            value={email}
                            onChange={(event) => setEmail(event.target.value)}
                            required
                        />
                    </div>
                    <div className="flex flex-col gap-1.5">
                        <Label htmlFor="password">Пароль</Label>
                        <Input
                            id="password"
                            type="password"
                            value={password}
                            onChange={(event) => setPassword(event.target.value)}
                            required
                        />
                    </div>
                </div>

                {error && <p className="mt-3 text-sm text-destructive">{error}</p>}

                <Button type="submit" className="mt-4 w-full" disabled={busy}>
                    {busy ? "Вход…" : "Войти"}
                </Button>
            </form>
        </div>
    );
}