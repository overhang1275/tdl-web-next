import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { encode } from "@auth/core/jwt";

const screenshots = path.resolve("../docs/design-audit/screenshots", process.env.AUDIT_RUN ?? "validation");
fs.mkdirSync(screenshots, { recursive: true });

test("login page renders the Authentik handoff", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Inicia sesión" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Continuar con Authentik/ })).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.screenshot({ path: path.join(screenshots, "login-1280.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(screenshots, "login-390.png"), fullPage: true });
});

test("private routes return to login", async ({ page }) => {
  for (const route of ["/", "/downloads", "/chats", "/settings"]) {
    await page.goto(route);
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByRole("button", { name: /Continuar con Authentik/ })).toBeVisible();
  }
  const response = await page.request.get("/api/v1/jobs");
  expect(response.status()).toBe(401);
  expect((await response.json()).error.code).toBe("unauthorized");
});

test("expired credentials stay on login without a redirect loop", async ({ page, baseURL }) => {
  const token = await encode({
    secret: "playwright-test-secret-at-least-32-characters",
    salt: "authjs.session-token", maxAge: 3600,
    token: { sub: "expired", accessToken: "expired-token", expiresAt: 1 },
  });
  await page.context().addCookies([{ name: "authjs.session-token", value: token, url: baseURL!, httpOnly: true }]);
  await page.goto("/");
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByRole("heading", { name: "Inicia sesión" })).toBeVisible();
});
