import { defineConfig, devices } from "@playwright/test";

const baseURL = process.env.E2E_BASE_URL ?? "http://localhost";

export default defineConfig({
    testDir: "./e2e",
    // стек поднимается в globalSetup (docker compose up -d --build + ожидание
    // /healthz): webServer для этого не годится - он считает выход процесса ошибкой,
    // а `compose up -d` отцепляется и выходит сразу
    globalSetup: "./e2e/global-setup.ts",
    fullyParallel: false,
    workers: 1,
    retries: process.env.CI ? 1 : 0,
    reporter: [["list"]],
    use: {
        baseURL,
        trace: "on-first-retry",
    },
    projects: [
        {
            name: "chromium",
            use: {
                ...devices["Desktop Chrome"],
                // 1600x900: ширина из инструкции по скриншотам (UI.2),
                // высота - чтобы влезали шапка и лента шагов
                viewport: { width: 1600, height: 900 },
            },
        },
    ],
});
