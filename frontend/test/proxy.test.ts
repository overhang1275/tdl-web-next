// @vitest-environment node
import { encode } from "next-auth/jwt";
import { NextRequest, type NextFetchEvent, type NextMiddleware } from "next/server";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";

const secret = "test-secret-with-at-least-thirty-two-characters";
const origin = "https://tld.example.test";
let proxy: NextMiddleware;

beforeAll(async () => {
  vi.stubEnv("AUTH_SECRET", secret);
  vi.stubEnv("AUTH_URL", "https://identity.example.test");
  vi.stubEnv("AUTHENTIK_ISSUER", "https://identity.example.test/application/o/tdl/");
  vi.stubEnv("AUTHENTIK_CLIENT_ID", "tdl");
  vi.stubEnv("AUTHENTIK_CLIENT_SECRET", "test-client-secret");
  proxy = (await import("@/proxy")).default;
});
afterAll(() => vi.unstubAllEnvs());

async function request(path: string, expiresAt?: number) {
  const headers = new Headers();
  if (expiresAt !== undefined) {
    const cookie = await encode({
      secret, salt: "__Secure-authjs.session-token", maxAge: 3600,
      token: { sub: "operator", name: "Operator", accessToken: "test-access-token", expiresAt },
    });
    headers.set("cookie", `__Secure-authjs.session-token=${cookie}`);
  }
  return proxy(new NextRequest(`${origin}${path}`, { headers }), {} as NextFetchEvent);
}

describe("app login redirects", () => {
  it("keeps root login on the requested TDL origin even with an incorrect AUTH_URL", async () => {
    const response = await request("/");
    expect(response?.headers.get("location")).toBe(`${origin}/login?callbackUrl=${encodeURIComponent(origin + "/")}`);
  });

  it("preserves a deep app destination without redirecting to the identity host", async () => {
    const response = await request("/downloads?page=2");
    const target = new URL(response!.headers.get("location")!);
    expect(target.origin).toBe(origin);
    expect(target.pathname).toBe("/login");
    expect(target.searchParams.get("callbackUrl")).toBe(`${origin}/downloads?page=2`);
  });

  it("allows an authenticated visitor", async () => {
    const response = await request("/", Date.now() / 1000 + 3600);
    expect(response?.headers.get("location")).toBeNull();
  });

  it("sends expired sessions to the TDL login page", async () => {
    const response = await request("/", 1);
    expect(new URL(response!.headers.get("location")!).origin).toBe(origin);
  });

  it("uses the public Host instead of the server bind address or forwarded-host input", async () => {
    const response = await proxy(new NextRequest("https://0.0.0.0:3000/", {
      headers: { host: "tld.example.test", "x-forwarded-host": "evil.test" },
    }), {} as NextFetchEvent);
    const location = new URL(response!.headers.get("location")!);
    expect(location.origin).toBe(origin);
    expect(location.searchParams.get("callbackUrl")).toBe(`${origin}/`);
  });
});
