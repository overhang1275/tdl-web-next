// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { auth, signIn } = vi.hoisted(() => ({ auth: vi.fn(), signIn: vi.fn() }));
vi.mock("@/auth", () => ({ auth, signIn }));
import { GET } from "@/app/login/route";

describe("automatic OIDC entry", () => {
  beforeEach(() => {
    vi.stubEnv("AUTH_URL", "https://tld.example.test");
    auth.mockReset().mockResolvedValue(null);
    signIn.mockReset().mockResolvedValue("https://identity.example.test/application/o/authorize/?state=protected");
  });
  afterEach(() => vi.unstubAllEnvs());

  it("starts Authentik directly for an anonymous visitor", async () => {
    const response = await GET(new NextRequest("https://tld.example.test/login"));
    expect(signIn).toHaveBeenCalledWith("authentik", { redirect: false, redirectTo: "https://tld.example.test/" });
    expect(response.headers.get("location")).toContain("https://identity.example.test/application/o/authorize/");
  });

  it("returns an authenticated visitor to the requested app route", async () => {
    auth.mockResolvedValue({ user: { name: "Operator" } });
    const response = await GET(new NextRequest("https://tld.example.test/login?callbackUrl=%2Fdownloads%3Fpage%3D2"));
    expect(response.headers.get("location")).toBe("https://tld.example.test/downloads?page=2");
    expect(signIn).not.toHaveBeenCalled();
  });

  it.each(["https://evil.test/", "//evil.test/", "/\\evil.test/"])("rejects an external return URL: %s", async (callbackUrl) => {
    await GET(new NextRequest(`https://tld.example.test/login?callbackUrl=${encodeURIComponent(callbackUrl)}`));
    expect(signIn).toHaveBeenCalledWith("authentik", { redirect: false, redirectTo: "https://tld.example.test/" });
  });

  it("restarts OIDC when session renewal failed", async () => {
    auth.mockResolvedValue({ user: { name: "Operator" }, error: "RefreshTokenError" });
    await GET(new NextRequest("https://tld.example.test/login"));
    expect(signIn).toHaveBeenCalledOnce();
  });

  it("never reparses a same-origin double slash path as an external host", async () => {
    auth.mockResolvedValue({ user: { name: "Operator" } });
    const callback = "https://tld.example.test//evil.test/";
    const response = await GET(new NextRequest(`https://tld.example.test/login?callbackUrl=${encodeURIComponent(callback)}`));
    expect(new URL(response.headers.get("location")!).origin).toBe("https://tld.example.test");
  });

  it("does not restart authentication after a provider denial", async () => {
    const response = await GET(new NextRequest("https://tld.example.test/login?error=OAuthCallbackError"));
    expect(signIn).not.toHaveBeenCalled();
    expect(new URL(response.headers.get("location")!).pathname).toBe("/signed-out");
  });
});
