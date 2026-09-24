import { expect, test } from "@playwright/test";

/**
 * Сквозной сценарий: регистрация → workspace → создание workflow →
 * сборка графа (Manual → Debug) → сохранение → публикация → статус active.
 * Требует поднятого стека (docker compose up -d).
 */
test("register, build graph, save and publish", async ({ page }) => {
    const email = `e2e-${Date.now()}@example.com`;
    const password = "test-password-123";

    // 1-2. регистрация
    await page.goto("/login");
    await page.getByTestId("auth-mode-toggle").click();
    await page.getByLabel("Email").fill(email);
    await page.getByLabel("Пароль").fill(password);
    await page.getByLabel("Имя").fill("E2E");
    await page.getByRole("button", { name: "Зарегистрироваться" }).click();

    // 3. попали на список workspace'ов
    await expect(page).toHaveURL(/\/workspaces$/);
    await expect(page.getByText("E2E's workspace")).toBeVisible();
    await page.getByText("E2E's workspace").click();

    // 4. создаём workflow
    await expect(page).toHaveURL(/\/workflows$/);
    await page.getByTestId("create-workflow").click();
    await page.getByTestId("workflow-name-input").fill("E2E test");
    await page.getByTestId("confirm-create-workflow").click();

    // 5. попали в редактор
    await expect(page).toHaveURL(/\/edit$/);
    const canvas = page.locator(".react-flow__pane");
    await expect(canvas).toBeVisible();

    // 6-7. перетаскиваем узлы из палитры на канвас.
    // Разносим по горизонтали: сложенные по вертикали узлы перекрываются, и
    // target-handle нижнего оказывается под телом верхнего — соединение не проходит
    await dragToCanvas(page, "trigger_manual", 360, 220);
    await dragToCanvas(page, "debug", 680, 220);
    await expect(page.locator(".react-flow__node")).toHaveCount(2);

    // 8. соединяем: тянем от source-handle триггера к target-handle дебага.
    // узлы ищем по подписям, а не по DOM-индексу — React Flow переупорядочивает DOM
    const triggerNode = page.locator(".react-flow__node", { hasText: "Manual Trigger" });
    const debugNode = page.locator(".react-flow__node", { hasText: "Debug" });
    await connectNodes(page, triggerNode, debugNode);
    await expect(page.locator(".react-flow__edge")).toHaveCount(1);

    // 8b. заполняем обязательный параметр Debug через панель параметров —
    // без него бэкенд отклоняет граф при сохранении (422)
    await debugNode.click();
    await page.getByTestId("param-message").fill("e2e");
    await expect(page.getByTestId("param-message")).toHaveValue("e2e");

    // 9. сохраняем
    await page.getByTestId("save-button").click();
    await expect(page.getByTestId("toast-success").filter({ hasText: "Saved v1" })).toBeVisible();

    // 10. публикуем
    await page.getByTestId("publish-button").click();
    await page.getByTestId("publish-confirm").click();
    await expect(
        page.getByTestId("toast-success").filter({ hasText: "Published v1" }),
    ).toBeVisible();

    // 11. возвращаемся в список — статус active
    await page.getByRole("link", { name: "← Назад" }).click();
    await expect(page).toHaveURL(/\/workflows$/);
    await expect(page.getByTestId("workflow-status-E2E test")).toHaveText("active");
});

/** Перетаскивание узла палитры на канвас (HTML5 drag-n-drop через dataTransfer). */
async function dragToCanvas(
    page: import("@playwright/test").Page,
    nodeType: string,
    x: number,
    y: number,
) {
    const paletteItem = page.getByTestId(`palette-${nodeType}`);
    const canvas = page.locator(".react-flow__pane");
    const box = await canvas.boundingBox();
    if (!box) throw new Error("canvas has no bounding box");

    await paletteItem.dragTo(canvas, {
        targetPosition: { x: x - box.x, y: y - box.y },
    });
}

/** Соединение узлов: mouse-протяжка между центрами source- и target-handle. */
async function connectNodes(
    page: import("@playwright/test").Page,
    sourceNode: import("@playwright/test").Locator,
    targetNode: import("@playwright/test").Locator,
) {
    const sourceBox = await sourceNode.locator(".react-flow__handle.source").boundingBox();
    const targetBox = await targetNode.locator(".react-flow__handle.target").boundingBox();
    if (!sourceBox || !targetBox) throw new Error("handle has no bounding box");

    const from = { x: sourceBox.x + sourceBox.width / 2, y: sourceBox.y + sourceBox.height / 2 };
    const to = { x: targetBox.x + targetBox.width / 2, y: targetBox.y + targetBox.height / 2 };

    await page.mouse.move(from.x, from.y);
    await page.mouse.down();
    await page.mouse.move(to.x, to.y, { steps: 15 });
    await page.mouse.up();
}