import NextAuth from "next-auth";
import { handlers, getAuthConfig } from "@/auth";
import { createHash } from "node:crypto";
import { type NextRequest } from "next/server";
import { AuthApiError, logoutSession } from "@/lib/auth-api";
import { appURL, authError, privateToken } from "@/lib/auth-session";

export const { GET } = handlers;

export async function POST(request: NextRequest) {
  if (request.nextUrl.pathname === "/api/auth/signout") {
    const body = request.headers.get("content-type")?.includes("application/json")
      ? await request.clone().json().catch(() => null)
      : Object.fromEntries(await request.clone().formData().catch(() => new FormData()));
    const cookie = request.cookies.get("__Host-authjs.csrf-token")?.value ?? request.cookies.get("authjs.csrf-token")?.value;
    const [csrf, hash] = cookie?.split("|") ?? [];
    if (!csrf || body?.csrfToken !== csrf || createHash("sha256").update(csrf + process.env.AUTH_SECRET).digest("hex") !== hash) {
      return authError("csrf_invalid", "Petición no autorizada.", 403);
    }
    const token = await privateToken(request);
    if (token) {
      try { await logoutSession(token.accessToken, token.refreshToken); }
      catch (error) { return authError("auth_unavailable", error instanceof AuthApiError ? error.message : "Intenta de nuevo.", 503); }
    }
    // Revocation has succeeded; prevent the Auth.js event from making a second fallible call.
    const response = await NextAuth({ ...getAuthConfig(), events: {} }).handlers.POST(request);
    const target = new URL("/login", appURL(request)).href;
    if (response.status >= 400) return response;
    if (request.headers.has("x-auth-return-redirect")) return Response.json({ url: target }, { status: response.status, headers: response.headers });
    response.headers.set("location", target);
    return response;
  }
  return handlers.POST(request);
}
