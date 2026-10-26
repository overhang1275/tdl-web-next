import { expect, test } from "@playwright/test";

test.skip(!process.env.E2E_INTEGRATION, "Requires the isolated Docker stack with OIDC and fake tdl.");

test("OIDC login, real API, Redis worker, download and persisted deletion", async ({ page, baseURL }) => {
  test.setTimeout(120_000);
  await page.goto("/login");
  await page.getByRole("button", { name: /Continuar con Authentik/ }).click();
  await expect(page.getByRole("heading", { name: "Resumen" })).toBeVisible();
  const session = await (await page.request.get("/api/auth/session")).json();
  expect(session.user.name).toBe("Operador de pruebas");
  expect(JSON.stringify(session)).not.toMatch(/accessToken|refreshToken|access_token|refresh_token/);
  expect((await page.context().cookies()).filter((cookie) => cookie.name.includes("session-token")).every((cookie) => cookie.httpOnly)).toBe(true);
  await page.goto("/downloads/new");
  await page.locator("#chat-id").fill("123");
  const created = page.waitForResponse((response) => response.url().endsWith("/api/v1/jobs") && response.request().method() === "POST");
  await page.getByRole("button", { name: "Crear descarga" }).click();
  const creation = await created;
  expect(creation.status()).toBe(201);
  const job = await creation.json();
  await expect(page).toHaveURL(new RegExp(`/downloads/${job.id}$`));
  await expect.poll(async () => (await (await page.request.get(`/api/v1/jobs/${job.id}`)).json()).status, { timeout: 60_000 }).toBe("completed");
  const files = await (await page.request.get(`/api/v1/jobs/${job.id}/files`)).json();
  expect(files.total).toBe(3);
  const downloaded = await page.request.get(files.items[0].download_url);
  expect(await downloaded.text()).toBe("complete");
  expect(downloaded.headers()["x-content-type-options"]).toBe("nosniff");
  await page.reload();
  await page.getByRole("button", { name: "Eliminar", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Eliminar job", exact: true }).click();
  await expect.poll(async () => (await page.request.get(`/api/v1/jobs/${job.id}`)).status(), { timeout: 60_000 }).toBe(404);
  const forged = await page.request.post("/api/v1/jobs", { headers: { origin: "https://evil.test", "x-requested-with": "tdl-web" }, data: {} });
  expect(forged.status()).toBe(403);
  expect(baseURL).toBe("http://web:3000");
});
