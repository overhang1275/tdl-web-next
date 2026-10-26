import { encode } from "@auth/core/jwt";
import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:3100";
const secret = "playwright-test-secret-at-least-32-characters";
const screenshots = path.resolve("../docs/design-audit/screenshots", process.env.AUDIT_RUN ?? "validation");
fs.mkdirSync(screenshots, { recursive: true });

const job = {
  id: 1,
  chat_id: "-1001234567890",
  chat_title: "Archivo de medios",
  hashtag: "#demo",
  media_type: "video",
  search_text: null,
  date_from: null,
  date_to: null,
  skip_same: true,
  refresh_export: true,
  export_only: false,
  output_subfolder: "videos",
  status: "running",
  stage: "downloading",
  total_filtered_messages: 120,
  total_downloaded_files: 50,
  total_failed_files: 2,
  transfer_initialized: true,
  downloaded_bytes: 52428800,
  total_expected_bytes: 125829120,
  speed_bps: 1048576,
  eta_seconds: 70,
  progress_percent: 41.7,
  error_message: null,
  created_at: "2026-10-26T08:00:00",
  started_at: "2026-10-26T08:01:00",
  finished_at: null,
  queue_position: null,
  deletion_requested: false,
  deletion_error: null,
};

const file = {
  file_id: 10,
  message_id: "10",
  name: "video.mp4",
  relative_path: "job-1/10/video.mp4",
  size: 52428800,
  human_size: "50.0 MB",
  kind: "video",
  modified_at: 1761465600,
  modified_label: "2026-10-26 08:00",
  can_preview: true,
  status: "completed",
  attempts: 1,
  last_error: null,
  content_url: "/api/v1/jobs/1/files/10/content",
  download_url: "/api/v1/jobs/1/files/10/content?download=true",
};

const chats = [
  { id: "-1001234567890", title: "Archivo de medios", username: "media_archive", type: "channel", topics_count: 0 },
  { id: "-1009876543210", title: "Equipo de producto", username: "", type: "group", topics_count: 3 },
  { id: "123456789", title: "Notas personales", username: "notes", type: "private", topics_count: 0 },
];

const status = {
  environment: "production",
  version: "1.0.0",
  session_active: true,
  session_error: null,
  tdl_installed: true,
  tdl_binary: "/usr/local/bin/tdl",
  redis_connected: true,
  redis_error: null,
  worker_connected: true,
  worker_count: 1,
  storage: "/data/sessions/tdl-data",
  can_start_services: false,
  authentik_configured: true,
};

async function authenticate(page: Page) {
  const token = await encode({
    token: {
      sub: "admin",
      name: "Admin",
      email: "admin@example.com",
      accessToken: "fixture-access-token",
      expiresAt: Math.floor(Date.now() / 1000) + 3600,
      groups: ["tdl-admin"],
    },
    secret,
    salt: "authjs.session-token",
    maxAge: 3600,
  });
  await page.context().addCookies([
    {
      name: "authjs.session-token",
      value: token,
      url: baseURL,
      httpOnly: true,
      sameSite: "Lax",
      secure: false,
    },
  ]);
}

async function mockApi(page: Page) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const pathname = url.pathname;
    const json = (body: unknown, statusCode = 200) =>
      route.fulfill({ status: statusCode, contentType: "application/json", body: JSON.stringify(body) });
    if (pathname === "/api/v1/dashboard") {
      return json({
        active_jobs: 1,
        failed_jobs: 0,
        downloaded_files: 50,
        disk_usage: "1.2 GB",
        latest_errors: [],
        chat_counts: { channels: 2, groups: 1, private: 0, total: 3, cached_at: "2026-10-26T08:00:00" },
      });
    }
    if (pathname === "/api/v1/status") return json(status);
    if (pathname === "/api/v1/auth/me") {
      return json({
        username: "admin",
        email: "admin@example.com",
        name: "Admin",
        groups: ["tdl-admin"],
        expires_at: "2026-10-26T18:00:00Z",
      });
    }
    if (pathname === "/api/v1/jobs/1/files") {
      return json({ items: [file], page: 1, per_page: 100, total: 1, page_count: 1 });
    }
    if (pathname === "/api/v1/jobs/1/logs") {
      return json({ content: "[2026-10-26T08:01:00Z] Descargando lote de 50 archivos\n", truncated: false });
    }
    if (pathname === "/api/v1/jobs/1/events") {
      return json([{ title: "Descarga iniciada", timestamp: "2026-10-26T08:01:00Z", message: "Lote de 50 archivos" }]);
    }
    if (pathname === "/api/v1/jobs/1") return json(job);
    if (pathname === "/api/v1/jobs") {
      return json({ items: [job], page: 1, per_page: 20, total: 1, page_count: 1 });
    }
    if (pathname === "/api/v1/chats") {
      return json({
        items: chats,
        page: 1,
        per_page: 25,
        total: 3,
        page_count: 1,
        q: "",
        chat_type: "",
        sort: "json",
        type_counts: { channel: 1, group: 1, private: 1, other: 0 },
        cached_at: "2026-10-26T08:00:00",
        refreshed: false,
      });
    }
    if (pathname.startsWith("/api/v1/chats/")) {
      return json({
        chat: chats[0],
        chat_id: chats[0].id,
        chat_title: chats[0].title,
        jobs: [job],
        export_exists: true,
        export_updated_at: "2026-10-26T08:00:00",
        downloaded_files: 50,
        downloaded_size: "1.2 GB",
        download_root: "/data/downloads/1001234567890",
      });
    }
    if (pathname === "/api/v1/templates") return json([]);
    if (pathname === "/api/v1/settings") {
      return json({
        app: { name: "TDL Console", version: "1.0.0", environment: "production" },
        paths: { data_dir: "/data", downloads_dir: "/data/downloads" },
        limits: { download_batch_size: 100, export_batch_size: 5000 },
        tdl: { binary: "/usr/local/bin/tdl", namespace: "default" },
        authentik: {
          issuer: "https://auth.example.com/application/o/tdl-console",
          audience: "tdl-console",
          admin_group: "tdl-admin",
        },
        can_start_services: false,
      });
    }
    if (pathname === "/api/v1/search") {
      return json({
        chats: [{ id: chats[0].id, title: chats[0].title, subtitle: "channel", url: `/chats/${chats[0].id}` }],
        jobs: [{ id: 1, title: "Job #1", subtitle: "running", url: "/downloads/1" }],
        files: [
          {
            id: 10,
            title: "video.mp4",
            subtitle: "Archivo de medios · 50.0 MB",
            url: "/downloads/1?file=10",
            download_url: "/api/v1/jobs/1/files/10/content?download=true",
          },
        ],
      });
    }
    if (pathname === "/api/v1/telegram/login") {
      return json({ running: false, output: ["Login no iniciado."], returncode: null, error: null, started_at: null, finished_at: null });
    }
    return json({ error: { code: "not_found", message: "Fixture no encontrada", detail: null } }, 404);
  });
}

test.beforeEach(async ({ page }) => {
  await authenticate(page);
  await mockApi(page);
});

test("templates can be saved, updated and deleted", async ({ page }) => {
  let saved: Record<string, unknown>[] = [];
  await page.route("**/api/v1/templates**", async (route) => {
    const request = route.request();
    if (request.method() === "GET") return route.fulfill({ json: saved });
    if (request.method() === "DELETE") { saved = []; return route.fulfill({ status: 204 }); }
    saved = [{ ...request.postDataJSON(), id: 1 }];
    return route.fulfill({ status: request.method() === "POST" ? 201 : 200, json: saved[0] });
  });
  await page.goto("/downloads/new");
  await page.getByLabel("Nombre de la plantilla").fill("Vídeos del canal");
  await page.getByRole("button", { name: "Guardar nueva" }).click();
  await expect(page.getByLabel("Plantilla guardada")).toHaveValue("1");
  await page.getByLabel("Nombre de la plantilla").fill("Archivo actualizado");
  await page.getByRole("button", { name: "Actualizar plantilla" }).click();
  await expect(page.getByLabel("Plantilla guardada").locator("option:checked")).toHaveText("Archivo actualizado");
  await page.getByRole("button", { name: "Eliminar plantilla", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Eliminar plantilla", exact: true }).click();
  await expect(page.getByLabel("Plantilla guardada")).toHaveValue("");
  expect(saved).toHaveLength(0);
});

test("file gallery reaches later pages", async ({ page }) => {
  await page.route("**/api/v1/jobs/1/files?**", (route) => {
    const current = Number(new URL(route.request().url()).searchParams.get("page") ?? 1);
    return route.fulfill({ json: { items: [{ ...file, name: current === 1 ? "first.mp4" : "last.mp4" }], page: current, per_page: 24, total: 25, page_count: 2 } });
  });
  await page.goto("/downloads/1");
  await expect(page.getByText("first.mp4")).toBeVisible();
  await page.getByRole("button", { name: "Página siguiente" }).click();
  await expect(page.getByText("last.mp4")).toBeVisible();
});

test("keyboard entry, mobile search and dark mode remain usable", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByText("1.2 GB")).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Saltar al contenido" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("main")).toBeFocused();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("link", { name: "Buscar" , exact: true })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole("button", { name: "Usar tema oscuro" }).click();
  await expect(page.locator("html")).toHaveClass(/dark/);
  await page.screenshot({ path: path.join(screenshots, "audit-dark-390.png"), fullPage: true });
});

test("empty, error, form validation and deletion confirmation states", async ({ page }) => {
  await page.route("**/api/v1/jobs?**", (route) => route.fulfill({ json: { items: [], total: 0, page: 1, per_page: 20, page_count: 1 } }));
  await page.goto("/downloads");
  await expect(page.getByText("No hay descargas", { exact: true })).toBeVisible();
  await page.screenshot({ path: path.join(screenshots, "audit-empty-1280.png"), fullPage: true });
  await page.route("**/api/v1/jobs?**", (route) => route.fulfill({ status: 503, json: { error: { code: "unavailable", message: "La API no está disponible." } } }));
  await page.reload();
  await expect(page.getByRole("alert").filter({ hasText: "La API no está disponible." })).toBeVisible();
  await expect(page.getByRole("button", { name: "Reintentar" })).toBeVisible();
  await page.screenshot({ path: path.join(screenshots, "audit-error-1280.png"), fullPage: true });
  await page.goto("/downloads/new");
  await page.getByRole("button", { name: /Crear/ }).click();
  await expect(page.getByText("Elige un chat o escribe su ID.")).toBeVisible();
  await expect(page.locator("#chat-id")).toBeFocused();
  await page.goto("/downloads/1");
  await page.getByRole("button", { name: "Eliminar", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Esta acción no se puede deshacer");
  await page.screenshot({ path: path.join(screenshots, "audit-confirm-1280.png"), fullPage: true });
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await expect(page.getByRole("button", { name: "Eliminar", exact: true })).toBeFocused();
});

test("summary, downloads, detail, chats, settings and responsive", async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Resumen" })).toBeVisible();
  await expect(page.getByText("1.2 GB")).toBeVisible();
  await expect(page.getByText("Archivo de medios").first()).toBeVisible();
  await page.screenshot({ path: path.join(screenshots, "01-resumen-1280.png"), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.screenshot({ path: path.join(screenshots, "02-resumen-1440.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: path.join(screenshots, "03-resumen-390.png"), fullPage: true });

  await page.setViewportSize({ width: 1280, height: 800 });
  await page.goto("/downloads");
  await expect(page.getByRole("heading", { name: "Descargas" })).toBeVisible();
  await expect(page.getByText("Archivo de medios").first()).toBeVisible();
  await page.screenshot({ path: path.join(screenshots, "04-descargas-1280.png"), fullPage: true });

  await page.goto("/downloads/1");
  await expect(page.getByRole("heading", { name: /Job #1/ })).toBeVisible();
  await expect(page.getByText("Progreso")).toBeVisible();
  await expect(page.getByText("Archivo de medios").first()).toBeVisible();
  await page.screenshot({ path: path.join(screenshots, "05-detalle-1280.png"), fullPage: true });

  await page.goto("/downloads/new");
  await expect(page.getByRole("heading", { name: "Nueva descarga" })).toBeVisible();
  await expect(page.getByText("Origen")).toBeVisible();
  await page.screenshot({ path: path.join(screenshots, "06-nueva-1280.png"), fullPage: true });

  await page.goto("/chats");
  await expect(page.getByRole("heading", { name: "Chats" })).toBeVisible();
  await expect(page.getByText("Equipo de producto").first()).toBeVisible();
  await page.screenshot({ path: path.join(screenshots, "07-chats-1280.png"), fullPage: true });

  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Configuración" })).toBeVisible();
  await expect(page.getByText("1.0.0").first()).toBeVisible();
  await page.screenshot({ path: path.join(screenshots, "08-settings-1280.png"), fullPage: true });

  await page.goto("/logs");
  await expect(page.getByRole("heading", { name: "Registros" })).toBeVisible();
  await expect(page.getByText("Archivo de medios").first()).toBeVisible();
  await page.screenshot({ path: path.join(screenshots, "09-registros-1280.png"), fullPage: true });
});
