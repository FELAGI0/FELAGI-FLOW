import { expect, test, type Page } from "@playwright/test";

/**
 * UI.2 - генерация скриншотов для README (docs/screenshots/README.md).
 *
 * Полный сценарий: регистрация -> dark -> credential -> workflow
 * Cron -> HTTP -> LLM -> Telegram -> publish -> run -> 4 PNG.
 *
 * Если env не задан (E2E_USER_.../E2E_TELEGRAM_...), тест логирует warning
 * и снимает "скелетные" экраны без данных - их всё равно можно использовать
 * как заглушки README. Запуск:
 *
 *   cd frontend
 *   E2E_BASE_URL=https://felagi-flow.vercel.app npx playwright test screenshots.spec.ts
 */
const SHOTS_DIR = "../docs/screenshots";

const WORKFLOW_NAME = "Screenshots Demo";
const CREDENTIAL_NAME = "Мой бот";

const HTTP_URL = "https://httpbin.org/get";
const LLM_PROMPT = "Say hello";
const TELEGRAM_TEXT = "Hello from Felagi Flow screenshots";

interface Creds {
    email: string;
    password: string;
    telegramToken?: string;
    telegramChatId?: string;
}

function readCreds(): Creds {
    const email = process.env.E2E_USER_EMAIL;
    const password = process.env.E2E_USER_PASSWORD;
    const telegramToken = process.env.E2E_TELEGRAM_TOKEN;
    const telegramChatId = process.env.E2E_TELEGRAM_CHAT_ID;

    if (!email || !password) {
        console.warn(
            "[screenshots] E2E_USER_EMAIL/E2E_USER_PASSWORD не заданы — " +
                "регистрирую временного пользователя",
        );
    }

    const full = Boolean(telegramToken && telegramChatId);
    if (!full) {
        console.warn(
            "[screenshots] E2E_TELEGRAM_TOKEN/E2E_TELEGRAM_CHAT_ID не заданы — " +
                "скриншоты будут сделаны на пустых экранах (skeleton)",
        );
    }

    return {
        // уникальный email, чтобы прод не был завален одноразовыми аккаунтами
        email: email ?? `screenshots-${Date.now()}@example.com`,
        password: password ?? "test-password-123",
        telegramToken: full ? telegramToken : undefined,
        telegramChatId: full ? telegramChatId : undefined,
    };
}

/**
 * SPA-переход без перезагрузки: полный page.goto сбрасывает access-токен
 * (живёт в памяти), а App пока не рестартует сессию через refresh-cookie.
 * pushState + popstate обрабатываются BrowserRouter'ом как обычный back/forward.
 */
async function navigateInApp(page: Page, path: string) {
    await page.evaluate((url) => {
        window.history.pushState({}, "", url);
        window.dispatchEvent(new PopStateEvent("popstate", { state: {} }));
    }, path);
}

/** Дождаться тёмной темы: класс dark на <html>. */
async function ensureDark(page: Page) {
    await expect(page.locator("html")).toHaveClass(/(^|\s)dark(\s|$)/);
}

/** Регистрация нового пользователя или логин существующего. */
async function auth(page: Page, creds: Creds) {
    await page.goto("/login");
    const hasEnvUser = Boolean(process.env.E2E_USER_EMAIL && process.env.E2E_USER_PASSWORD);

    if (hasEnvUser) {
        await page.getByLabel("Email").fill(creds.email);
        await page.getByLabel("Пароль").fill(creds.password);
        await page.getByRole("button", { name: "Войти" }).click();
    } else {
        await page.getByTestId("auth-mode-toggle").click();
        await page.getByLabel("Email").fill(creds.email);
        await page.getByLabel("Пароль").fill(creds.password);
        await page.getByLabel("Имя").fill("Screenshots");
        await page.getByRole("button", { name: "Зарегистрироваться" }).click();
    }

    await expect(page).toHaveURL(/\/workspaces$/);
}

/** Циклом дойти до dark: light -> dark -> system -> light. */
async function switchToDark(page: Page) {
    const toggle = page.getByTestId("theme-toggle");
    await expect(toggle).toBeVisible();
    for (let i = 0; i < 3; i++) {
        if (await page.locator("html").evaluate((el) => el.classList.contains("dark"))) return;
        await toggle.click();
    }
    await ensureDark(page);
}

/** id workspace из URL /workspaces/{wsId}/... */
function wsIdOf(page: Page): string {
    const match = page.url().match(/\/workspaces\/([^/]+)/);
    if (!match) throw new Error(`workspace id not found in URL: ${page.url()}`);
    return match[1];
}

/** Перетащить узел из палитры на канвас. */
async function dragNode(page: Page, nodeType: string, x: number, y: number) {
    const canvas = page.locator(".react-flow__pane");
    const box = await canvas.boundingBox();
    if (!box) throw new Error("canvas has no bounding box");

    await page.getByTestId(`palette-${nodeType}`).dragTo(canvas, {
        targetPosition: { x: x - box.x, y: y - box.y },
    });
}

/** Соединить два узла протяжкой между handle'ами. */
async function connectNodes(page: Page, sourceText: string, targetText: string) {
    const source = page.locator(".react-flow__node", { hasText: sourceText });
    const target = page.locator(".react-flow__node", { hasText: targetText });

    const sourceBox = await source.locator(".react-flow__handle.source").boundingBox();
    const targetBox = await target.locator(".react-flow__handle.target").boundingBox();
    if (!sourceBox || !targetBox) throw new Error("handle has no bounding box");

    const from = {
        x: sourceBox.x + sourceBox.width / 2,
        y: sourceBox.y + sourceBox.height / 2,
    };
    const to = {
        x: targetBox.x + targetBox.width / 2,
        y: targetBox.y + targetBox.height / 2,
    };

    await page.mouse.move(from.x, from.y);
    await page.mouse.down();
    await page.mouse.move(to.x, to.y, { steps: 15 });
    await page.mouse.up();
}

/** Клик по узлу на канвасе по тексту. */
async function clickNode(page: Page, text: string) {
    await page.locator(".react-flow__node", { hasText: text }).click();
}

test("generate README screenshots in dark theme", async ({ page }) => {
    test.setTimeout(180_000);
    const creds = readCreds();

    // 1-2: авторизация + тёмная тема
    await auth(page, creds);
    await switchToDark(page);
    await ensureDark(page);

    // входим в workspace (после регистрации он ровно один)
    const workspaceLink = page.locator("main a[href^='/workspaces/']").first();
    await expect(workspaceLink).toBeVisible();
    await workspaceLink.click();
    await expect(page).toHaveURL(/\/workspaces\/[^/]+\/workflows$/);
    const wsId = wsIdOf(page);

    // 4: workflow Cron -> HTTP -> LLM -> Telegram
    await page.getByTestId("create-workflow").click();
    await page.getByTestId("workflow-name-input").fill(WORKFLOW_NAME);
    await page.getByTestId("confirm-create-workflow").click();
    await expect(page).toHaveURL(/\/edit$/);
    await expect(page.locator(".react-flow__pane")).toBeVisible();
    await ensureDark(page);

    // раскладка: горизонтальная цепочка по канвасу 1600x900
    const xs = [260, 560, 860, 1160];
    await dragNode(page, "trigger_cron", xs[0], 430);
    await dragNode(page, "action_http", xs[1], 430);
    await dragNode(page, "action_llm", xs[2], 430);
    await dragNode(page, "action_telegram", xs[3], 430);
    await expect(page.locator(".react-flow__node")).toHaveCount(4);

    await connectNodes(page, "Cron Trigger", "HTTP Request");
    await connectNodes(page, "HTTP Request", "LLM");
    await connectNodes(page, "LLM", "Telegram");
    await expect(page.locator(".react-flow__edge")).toHaveCount(3);

    // 3: credential (только с env-токеном) - через SPA-переход
    let hasCredential = false;
    if (creds.telegramToken && creds.telegramChatId) {
        await navigateInApp(page, `/workspaces/${wsId}/credentials`);
        await expect(page.getByTestId("create-credential")).toBeVisible();
        await page.getByTestId("create-credential").click();
        await page.getByTestId("credential-name").fill(CREDENTIAL_NAME);
        await page.getByTestId("credential-token").fill(creds.telegramToken);
        await page.getByTestId("confirm-create-credential").click();
        await expect(page.getByTestId(`credential-row-${CREDENTIAL_NAME}`)).toBeVisible();
        hasCredential = true;

        // обратно в редактор
        await page.getByRole("link", { name: "← Workflows" }).click();
        await expect(page).toHaveURL(/\/workflows$/);
        await page
            .locator("li", { hasText: WORKFLOW_NAME })
            .getByRole("link", { name: "Редактировать" })
            .click();
        await expect(page).toHaveURL(/\/edit$/);
    }

    // параметры Cron
    await clickNode(page, "Cron Trigger");
    await page.getByTestId("param-cron_expr").fill("*/15 * * * *");
    await page.getByTestId("param-timezone").fill("UTC");

    // параметры HTTP (httpbin)
    await clickNode(page, "HTTP Request");
    await page.getByTestId("param-url").fill(HTTP_URL);

    // параметры LLM
    await clickNode(page, "LLM");
    await page.getByTestId("param-model").fill("gpt-4o-mini");
    await page.getByTestId("param-prompt").fill(LLM_PROMPT);

    // параметры Telegram (credential + chat_id)
    await clickNode(page, "Telegram");
    await page.getByTestId("param-chat_id").fill(creds.telegramChatId ?? "123456789");
    await page.getByTestId("param-text").fill(TELEGRAM_TEXT);
    if (hasCredential) {
        await page.getByTestId("param-credential_id").click();
        await page.getByRole("option", { name: `${CREDENTIAL_NAME} (telegram)` }).click();
    }

    // 5: сохранить + опубликовать (только в полном режиме)
    if (hasCredential) {
        await page.getByTestId("save-button").click();
        await expect(
            page.getByTestId("toast-success").filter({ hasText: "Saved v1" }),
        ).toBeVisible({ timeout: 30_000 });

        await page.getByTestId("publish-button").click();
        await page.getByTestId("publish-confirm").click();
        await expect(
            page.getByTestId("toast-success").filter({ hasText: "Published v1" }),
        ).toBeVisible({ timeout: 30_000 });

        // 6: запустить execution - редирект на detail
        await page.getByTestId("run-button").click();
        await expect(page).toHaveURL(/\/executions\/[^/]+$/);

        // 7: дать worker'у отработать шаги
        await page.waitForTimeout(8_000);
    }

    // 8b: execution-live-dark.png - детали запуска (только в полном режиме)
    if (hasCredential) {
        await expect(page.getByText("Шаги")).toBeVisible();
        await page.waitForTimeout(2_000);
        await ensureDark(page);
        await page.screenshot({ path: `${SHOTS_DIR}/execution-live-dark.png`, fullPage: true });

        // ← Запуски -> ← Workflows -> Редактировать (всё SPA-ссылками)
        await page.getByRole("link", { name: "← Запуски" }).click();
        await expect(page).toHaveURL(/\/executions$/);
        await page.getByRole("link", { name: "← Workflows" }).click();
        await expect(page).toHaveURL(/\/workflows$/);
    } else {
        // skeleton: пустая execution-страница без запуска - снимем список
        await navigateInApp(page, `/workspaces/${wsId}/executions`);
        await ensureDark(page);
        await page.waitForTimeout(500);
        await page.screenshot({ path: `${SHOTS_DIR}/execution-live-dark.png`, fullPage: true });
        await navigateInApp(page, `/workspaces/${wsId}/workflows`);
    }

    // 8a: editor-dark.png - редактор с графом
    await page
        .locator("li", { hasText: WORKFLOW_NAME })
        .getByRole("link", { name: "Редактировать" })
        .click();
    await expect(page).toHaveURL(/\/edit$/);
    await expect(page.locator(".react-flow__node")).toHaveCount(4);
    await ensureDark(page);
    await page.screenshot({ path: `${SHOTS_DIR}/editor-dark.png`, fullPage: true });

    // 8d: node-panel-dark.png - панель параметров Telegram
    await clickNode(page, "Telegram");
    const upstream = page.getByTestId("upstream-details");
    if (await upstream.count() > 0) {
        await upstream.locator("summary").click();
    }
    const panel = page.locator("aside").last();
    await expect(panel.getByTestId("node-id")).toBeVisible();
    await panel.screenshot({ path: `${SHOTS_DIR}/node-panel-dark.png` });

    // 8c: credentials-dark.png
    await navigateInApp(page, `/workspaces/${wsId}/credentials`);
    await ensureDark(page);
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${SHOTS_DIR}/credentials-dark.png`, fullPage: true });
});
