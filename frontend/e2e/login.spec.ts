import { expect, test } from "@playwright/test";
import { encode } from "@auth/core/jwt";

test("login starts OIDC automatically with PKCE, state and an app callback", async ({ request, baseURL }) => {
  const response = await request.get("/login", { maxRedirects: 0 });
  expect(response.status()).toBe(307);
  const target = new URL(response.headers().location);
  expect(target.pathname).toBe("/application/o/authorize/");
  expect(target.searchParams.get("redirect_uri")).toBe(`${baseURL}/api/auth/callback/authentik`);
  expect(target.searchParams.get("state")).toBeTruthy();
  expect(target.searchParams.get("code_challenge_method")).toBe("S256");
  expect(target.searchParams.get("code_challenge")).toBeTruthy();
  const cookies = response.headersArray().filter((header) => header.name.toLowerCase() === "set-cookie");
  expect(cookies.length).toBeGreaterThan(0);
  expect(cookies.every((cookie) => /httponly/i.test(cookie.value))).toBe(true);
});

test("private routes enter the OIDC flow and API access remains protected", async ({ request }) => {
  for (const route of ["/", "/downloads", "/chats", "/settings"]) {
    const response = await request.get(route, { maxRedirects: 0 });
    expect(response.status()).toBe(307);
    expect(new URL(response.headers().location).pathname).toBe("/login");
    const login = await request.get(response.headers().location, { maxRedirects: 0 });
    expect(new URL(login.headers().location).pathname).toBe("/application/o/authorize/");
  }
  const response = await request.get("/api/v1/jobs");
  expect(response.status()).toBe(401);
  expect((await response.json()).error.code).toBe("unauthorized");
});

test("expired credentials restart OIDC and can establish a new session", async ({ page, baseURL }) => {
  const token = await encode({
    secret: "playwright-test-secret-at-least-32-characters",
    salt: "authjs.session-token", maxAge: 3600,
    token: { sub: "expired", accessToken: "expired-token", expiresAt: 1 },
  });
  await page.context().addCookies([{ name: "authjs.session-token", value: token, url: baseURL!, httpOnly: true }]);
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Resumen" })).toBeVisible();
});

test("health responds without triggering OIDC", async ({ request }) => {
  const response = await request.get("/health", { maxRedirects: 0 });
  expect(response.status()).toBe(200);
  expect(await response.json()).toEqual({ status: "ok" });
  expect(response.headers().location).toBeUndefined();
});

test("explicit logout stays signed out instead of automatically logging back in", async ({ page }) => {
  await page.goto("/login");
  await expect(page.getByRole("heading", { name: "Resumen" })).toBeVisible();
  await page.getByLabel("Menú de usuario").click();
  await page.getByRole("button", { name: "Cerrar sesión", exact: true }).click();
  await expect(page).toHaveURL(/\/signed-out$/);
  await expect(page.getByRole("heading", { name: "Sesión de TDL cerrada" })).toBeVisible();
  const session = await (await page.request.get("/api/auth/session")).json();
  expect(session?.user).toBeUndefined();
});

test("provider errors stop at an explicit retry page", async ({ page }) => {
  await page.goto("/login?error=OAuthCallbackError");
  await expect(page).toHaveURL(/\/signed-out\?error=authentication$/);
  await expect(page.getByRole("heading", { name: "No se pudo iniciar sesión" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Reintentar con Authentik" })).toHaveAttribute("href", "/login");
});
