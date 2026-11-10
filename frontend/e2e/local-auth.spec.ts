import { expect, test, type Page } from "@playwright/test";
import path from "node:path";
import fs from "node:fs";
test.skip(!process.env.E2E_INTEGRATION, "Requires isolated PostgreSQL test fixtures.");
const password = process.env.E2E_LOCAL_PASSWORD!;
async function login(page: Page, username = "local-admin", secret = password) {
  await page.goto("/login");
  await page.getByLabel("Usuario", { exact: true }).fill(username);
  await page.getByLabel("Contraseña", { exact: true }).fill(secret);
  await page.getByRole("button", { name: "Iniciar sesión", exact: true }).click();
}

test("wrong local credentials show an accessible error and allow retry", async ({ page }) => {
  await login(page, "local-admin", "wrong-test-password");
  await expect(page.locator("#login-error")).toContainText("Revisa tu usuario");
  await expect(page.getByRole("button", { name: "Iniciar sesión", exact: true })).toBeEnabled();
  const directory = path.resolve("../docs/design-audit/screenshots", process.env.AUDIT_RUN ?? "validation");
  fs.mkdirSync(directory, { recursive: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(directory, "login-error-390.png"), fullPage: true });
});

test("local login remains available and logout immediately revokes the saved cookie", async ({ page, browser }) => {
  await login(page);
  await expect(page.getByRole("heading", { name: "Resumen", exact: true })).toBeVisible();
  const saved = await page.context().storageState();
  expect((await page.request.post("/api/session/logout", { headers: { origin: "https://evil.test", "x-requested-with": "tdl-web" } })).status()).toBe(403);
  expect((await page.request.post("/api/session/logout")).status()).toBe(403);
  expect((await page.request.get("/api/v1/jobs")).status()).toBe(200);
  const native = await page.request.get("/api/auth/session");
  expect(JSON.stringify(await native.json())).not.toMatch(/accessToken|refreshToken|access_token|refresh_token/);
  await page.getByLabel("Menú de usuario").click();
  await page.getByRole("button", { name: "Cerrar sesión", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  const replay = await browser.newContext({ storageState: saved });
  expect((await replay.request.get("/api/v1/jobs")).status()).toBe(401);
  await replay.close();
});

test("user administration, forced change, reset and revocation", async ({ page, browser, baseURL }) => {
  test.setTimeout(120_000);
  await login(page);
  await expect(page.getByRole("heading", { name: "Resumen", exact: true })).toBeVisible();
  await page.goto("/users");
  const username = `created-${Date.now()}`;
  const temporary = "Temporary-only-password-2026";
  await page.getByLabel("Usuario", { exact: true }).fill(username);
  await page.getByLabel("Nombre visible", { exact: true }).fill("Cuenta de prueba");
  await page.getByLabel("Contraseña temporal", { exact: true }).fill(temporary);
  await page.getByRole("button", { name: "Crear usuario", exact: true }).click();
  await expect(page.getByRole("heading", { name: username, exact: true })).toBeVisible();
  const context = await browser.newContext({ baseURL }); const restricted = await context.newPage();
  await login(restricted, username, temporary);
  await expect(restricted).toHaveURL(/\/change-password$/);
  const evidence = path.resolve("../docs/design-audit/screenshots", process.env.AUDIT_RUN ?? "validation"); fs.mkdirSync(evidence, { recursive: true });
  await restricted.setViewportSize({ width: 390, height: 844 });
  await restricted.screenshot({ path: path.join(evidence, "password-390.png"), fullPage: true });
  expect((await restricted.request.get("/api/v1/jobs")).status()).toBe(403);
  await restricted.getByLabel("Contraseña actual", { exact: true }).fill(temporary);
  await restricted.getByLabel("Nueva contraseña", { exact: true }).fill("Changed-only-password-2026");
  await restricted.getByRole("button", { name: "Cambiar contraseña", exact: true }).click();
  await expect(restricted).toHaveURL(/\/login\?changed=1$/);
  await login(restricted, username, "Changed-only-password-2026");
  await expect(restricted.getByRole("heading", { name: "Resumen", exact: true })).toBeVisible();
  const card = page.locator("div.rounded-xl").filter({ has: page.getByRole("heading", { name: username, exact: true }) }).last();
  await card.getByRole("button", { name: "Revocar sesiones", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirmar", exact: true }).click();
  await expect.poll(async () => (await restricted.request.get("/api/v1/jobs")).status()).toBe(401);
  await card.getByRole("button", { name: "Restablecer contraseña", exact: true }).click();
  await page.getByLabel("Nueva contraseña temporal", { exact: true }).fill(temporary);
  await page.getByRole("button", { name: "Restablecer", exact: true }).click();
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await login(restricted, username, temporary); await expect(restricted).toHaveURL(/\/change-password$/);
  await card.getByRole("button", { name: "Desactivar", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirmar", exact: true }).click();
  await expect(card).toContainText("Desactivado");
  const screenshots = path.resolve("../docs/design-audit/screenshots", process.env.AUDIT_RUN ?? "validation"); fs.mkdirSync(screenshots, { recursive: true });
  await page.setViewportSize({ width: 1280, height: 800 }); await page.evaluate(() => window.scrollTo(0, 0)); await page.screenshot({ path: path.join(screenshots, "users-1280.png") });
  await page.setViewportSize({ width: 390, height: 844 }); await page.evaluate(() => window.scrollTo(0, 0)); await page.screenshot({ path: path.join(screenshots, "users-390.png") });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await context.close();
});

test("idle deadline rejects an unexpired cookie immediately", async ({ page, request }) => {
  await login(page, "idle-probe");
  await expect(page.getByRole("heading", { name: "Resumen", exact: true })).toBeVisible();
  expect((await request.post("http://auth-control:9001/expire-idle-probe")).status()).toBe(204);
  expect((await page.request.get("/api/v1/jobs")).status()).toBe(401);
  await page.goto("/"); await expect(page).toHaveURL(/\/login/);
});

test("last local account remains active and displays an understandable error", async ({ page }) => {
  await login(page); await expect(page.getByRole("heading", { name: "Resumen", exact: true })).toBeVisible();
  const users = await (await page.request.get("/api/v1/users")).json();
  for (const user of users) if (user.username !== "local-admin" && user.active && user.is_local) {
    expect((await page.request.patch(`/api/v1/users/${user.id}`, { headers: { "x-requested-with": "tdl-web" }, data: { active: false } })).status()).toBe(200);
  }
  await page.goto("/users");
  const card = page.locator("div.rounded-xl").filter({ has: page.getByRole("heading", { name: "local-admin", exact: true }) }).last();
  await card.getByRole("button", { name: "Desactivar", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Confirmar", exact: true }).click();
  await expect(page.getByText("Debe quedar al menos un administrador local activo.", { exact: true })).toBeVisible();
  await expect(card).toContainText("Activo");
  const probe = users.find((user: { username: string }) => user.username === "idle-probe");
  expect((await page.request.patch(`/api/v1/users/${probe.id}`, { headers: { "x-requested-with": "tdl-web" }, data: { active: true } })).status()).toBe(200);
});
