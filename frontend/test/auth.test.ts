// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getAuthConfig, handlers } from "@/auth";
import { encode } from "next-auth/jwt";
import { loginLocal, AuthApiError } from "@/lib/auth-api";

afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

describe("native authentication", () => {
  it.each(["//evil.test", "/\\evil.test", "/\n/evil.test", "https://evil.test"])("never redirects to a foreign callback: %s", async (url) => {
    const target = await getAuthConfig().callbacks!.redirect!({ url, baseUrl: "https://tdl.test" });
    expect(new URL(target).origin).toBe("https://tdl.test");
  });
  it("does not register or parse a disabled external provider", () => {
    vi.stubEnv("AUTHENTIK_ENABLED", "false");
    vi.stubEnv("AUTHENTIK_ISSUER", "malformed://[");
    const providers = getAuthConfig().providers.map((provider) => typeof provider === "function" ? provider().id : provider.id);
    expect(providers).toEqual(["credentials"]);
  });

  it("rejects ambiguous provider switches", () => {
    vi.stubEnv("AUTHENTIK_ENABLED", "yes");
    expect(() => getAuthConfig()).toThrow("AUTHENTIK_ENABLED");
  });

  it("serves only local credentials when external auth is disabled", async () => {
    vi.stubEnv("AUTH_SECRET", "test-secret-with-at-least-thirty-two-characters");
    vi.stubEnv("AUTH_URL", "http://localhost:3000");
    vi.stubEnv("AUTHENTIK_ENABLED", "false");
    const response = await handlers.GET(new NextRequest("http://localhost:3000/api/auth/providers"));
    expect(Object.keys(await response.json())).toEqual(["credentials"]);
  });

  it("reports upstream login failures without leaking upstream text", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ error: { code: "auth_unavailable", message: "secret-database-password" } }, { status: 503 })));
    await expect(loginLocal("operator", "private-password")).rejects.toMatchObject({ status: 503, code: "auth_unavailable" });
    try { await loginLocal("operator", "private-password"); } catch (error) {
      expect(error).toBeInstanceOf(AuthApiError);
      expect(String(error)).not.toContain("secret-database-password");
    }
  });

  it.each([503, 204, 401])("native signout revokes before clearing; upstream %s", async (status) => {
    vi.stubEnv("AUTH_SECRET", "test-secret-with-at-least-thirty-two-characters");
    vi.stubEnv("AUTH_URL", "http://identity.example.test");
    const csrf = await handlers.GET(new NextRequest("http://localhost:3000/api/auth/csrf"));
    const { csrfToken } = await csrf.json();
    const session = await encode({ secret: process.env.AUTH_SECRET!, salt: "authjs.session-token", token: { accessToken: "private-access", refreshToken: "private-proof", expiresAt: 1 } });
    const cookies = csrf.headers.getSetCookie().map((cookie) => cookie.split(";")[0]).join("; ") + `; authjs.session-token=${session}`;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(status === 204 ? new Response(null, { status }) : Response.json({ error: { code: "auth_unavailable" } }, { status })));
    const route = await import("@/app/api/auth/[...nextauth]/route");
    const response = await route.POST(new NextRequest("http://localhost:3000/api/auth/signout", { method: "POST", headers: { cookie: cookies, "content-type": "application/x-www-form-urlencoded", "x-auth-return-redirect": "1" }, body: new URLSearchParams({ csrfToken, callbackUrl: "/login" }) }));
    expect(response.status).toBe(status === 503 ? 503 : 200);
    const cleared = /Max-Age=0|1970/.test(response.headers.get("set-cookie") ?? "");
    expect(cleared).toBe(status !== 503);
    if (status !== 503) expect((await response.json()).url).toBe("http://localhost:3000/login");
  });
});
