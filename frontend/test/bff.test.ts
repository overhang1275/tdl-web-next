// @vitest-environment node
import { encode } from "next-auth/jwt";
import { NextRequest } from "next/server";
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const secret = "test-secret-with-at-least-thirty-two-characters";
const origin = "http://localhost:3000";
let routes: typeof import("@/app/api/v1/[...path]/route");
let authentication: typeof import("@/auth");
const fetchMock = vi.fn<typeof fetch>();

beforeAll(async () => {
  vi.stubEnv("AUTH_SECRET", secret);
  vi.stubEnv("AUTHENTIK_ISSUER", "https://auth.test/application/o/console");
  vi.stubEnv("AUTHENTIK_CLIENT_ID", "console");
  vi.stubEnv("AUTHENTIK_CLIENT_SECRET", "client-secret");
  vi.stubEnv("AUTH_URL", origin);
  vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
  routes = await import("@/app/api/v1/[...path]/route");
  authentication = await import("@/auth");
});
beforeEach(() => {
  fetchMock.mockReset();
  fetchMock.mockResolvedValue(Response.json({ ok: true }));
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());
afterAll(() => vi.unstubAllEnvs());

async function request(path: string, init: RequestInit = {}, token: Record<string, unknown> | null = {}) {
  const headers = new Headers(init.headers);
  if (token) {
    const cookie = await encode({
      secret, salt: "authjs.session-token", maxAge: 3600,
      token: { sub: "operator", accessToken: "server-access-token", expiresAt: Date.now() / 1000 + 3600, ...token },
    });
    headers.set("cookie", `authjs.session-token=${cookie}`);
  }
  return new NextRequest(`${origin}${path}`, { ...init, headers, signal: init.signal ?? undefined });
}

async function proxy(init: RequestInit = {}, token: Record<string, unknown> | null = {}) {
  const req = await request("/api/v1/jobs?page=2", init, token);
  const method = (init.method ?? "GET") as "GET" | "POST" | "DELETE";
  return routes[method](req, { params: Promise.resolve({ path: ["jobs"] }) });
}

describe("BFF authentication and forwarding", () => {
  it("returns JSON 401 without a session", async () => {
    const response = await proxy({}, null);
    expect(response.status).toBe(401);
    expect((await response.json()).error.code).toBe("unauthorized");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("forwards idempotency and server credentials without client cookies or authorization", async () => {
    const response = await proxy({ method: "POST", body: "{}", headers: {
      origin, "x-requested-with": "tdl-web", "idempotency-key": "request-123",
      authorization: "Bearer attacker", "content-type": "application/json",
    } });
    expect(response.status).toBe(200);
    const [url, init] = fetchMock.mock.calls.at(-1)!;
    expect(String(url)).toBe("http://api:8000/api/v1/jobs?page=2");
    const headers = new Headers(init?.headers);
    expect(headers.get("idempotency-key")).toBe("request-123");
    expect(headers.get("authorization")).toBe("Bearer server-access-token");
    expect(headers.has("cookie")).toBe(false);
  });

  it.each(["https://evil.test", "https://localhost:3000", "null"])("blocks a different origin: %s", async (foreignOrigin) => {
    const response = await proxy({ method: "POST", headers: { origin: foreignOrigin, "x-requested-with": "tdl-web" } });
    expect(response.status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects writes without the CSRF header", async () => {
    expect((await proxy({ method: "DELETE", headers: { origin } })).status).toBe(403);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refreshes an expired token and persists the rotated HttpOnly session", async () => {
    fetchMock.mockImplementation(async (url) => String(url).includes("/application/o/token/")
      ? Response.json({ access_token: "fresh-access", refresh_token: "rotated-refresh", expires_in: 300 })
      : Response.json({ ok: true }));
    const response = await proxy({}, { expiresAt: 1, refreshToken: "old-refresh" });
    expect(response.status).toBe(200);
    expect(String(fetchMock.mock.calls[0][0])).toBe("https://auth.test/application/o/token/");
    expect(new Headers(fetchMock.mock.calls.at(-1)![1]?.headers).get("authorization")).toBe("Bearer fresh-access");
    const cookies = response.headers.get("set-cookie") ?? "";
    expect(cookies).toContain("HttpOnly");
    expect(cookies).not.toContain("fresh-access");
    expect(cookies).not.toContain("rotated-refresh");
  });

  it("fails closed when refresh fails", async () => {
    fetchMock.mockResolvedValue(Response.json({ error: "invalid_grant" }, { status: 400 }));
    expect((await proxy({}, { expiresAt: 1, refreshToken: "revoked" })).status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shares one refresh when dashboard requests arrive together", async () => {
    let refreshes = 0;
    fetchMock.mockImplementation(async (url) => {
      if (!String(url).includes("/application/o/token/")) return Response.json({ ok: true });
      if (++refreshes > 1) return Response.json({ error: "invalid_grant" }, { status: 400 });
      await new Promise((resolve) => setTimeout(resolve, 30));
      return Response.json({ access_token: "fresh-access", refresh_token: "rotated", expires_in: 300 });
    });
    const responses = await Promise.all(Array.from({ length: 3 }, () => proxy({}, { expiresAt: 1, refreshToken: "shared-once" })));
    expect(responses.map((response) => response.status)).toEqual([200, 200, 200]);
    expect(refreshes).toBe(1);
  });

  it("rejects expired access tokens without a refresh token", async () => {
    expect((await proxy({}, { expiresAt: 1 })).status).toBe(401);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("never exposes OAuth tokens through the browser session endpoint", async () => {
    const response = await authentication.handlers.GET(await request("/api/auth/session", {}, { refreshToken: "private-refresh" }));
    const body = await response.text();
    expect(response.status).toBe(200);
    expect(body).not.toContain("server-access-token");
    expect(body).not.toContain("private-refresh");
    expect(body).not.toContain("accessToken");
  });

  it("returns 502 when the API is unreachable", async () => {
    fetchMock.mockRejectedValue(new Error("offline"));
    expect((await proxy()).status).toBe(502);
  });
});
