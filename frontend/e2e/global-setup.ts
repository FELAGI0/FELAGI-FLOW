import { execSync } from "node:child_process";

/**
 * Поднимает стек перед E2E: `docker compose up -d --build`.
 *
 * Именно globalSetup, а не webServer: Playwright трактует завершение процесса
 * webServer как ошибку ("Process from config.webServer exited early"), а
 * `docker compose up -d` намеренно отцепляется и выходит сразу. Здесь же команда
 * завершается штатно, а готовность стека мы опрашиваем сами.
 *
 * --build обязателен: без него E2E уже прошёл по устаревшему backend-образу
 * и выглядел зелёным (404 на /api/auth/register).
 */
const COMPOSE_FILE = "../docker-compose.yml";
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost";

async function waitForServer(url: string, timeoutMs = 180_000): Promise<void> {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
        try {
            const response = await fetch(`${url}/healthz`);
            if (response.ok) return;
        } catch {
            // сервер ещё не поднялся — ждём дальше
        }
        await new Promise((resolve) => setTimeout(resolve, 2000));
    }
    throw new Error(`stack did not become healthy at ${url}/healthz within ${timeoutMs}ms`);
}

export default async function globalSetup(): Promise<void> {
    if (process.env.E2E_SKIP_SETUP === "1") return;
    execSync(`docker compose -f ${COMPOSE_FILE} up -d --build`, { stdio: "inherit" });
    await waitForServer(BASE_URL);
}