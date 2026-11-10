import "server-only";
import NextAuth, { type NextAuthRequest } from "next-auth";
import { getToken } from "next-auth/jwt";
import { NextResponse, type NextRequest } from "next/server";
import { getAuthConfig } from "@/auth";

export function appURL(request: Request) {
  const url = new URL(request.url);
  const host = request.headers.get("host");
  if (host && /^[a-zA-Z0-9.[\]:-]+$/.test(host)) { url.port = ""; url.host = host; }
  const protocol = request.headers.get("x-forwarded-proto");
  if (protocol === "https" || protocol === "http") url.protocol = `${protocol}:`;
  return url;
}

export function authError(code: string, message: string, status: number) {
  return Response.json({ error: { code, message, detail: null } }, { status });
}

export function checkCSRF(request: Request) {
  const origin = request.headers.get("origin");
  if (origin && origin !== appURL(request).origin) return authError("cross_origin_blocked", "Origen no permitido.", 403);
  if (!["GET", "HEAD"].includes(request.method) && request.headers.get("x-requested-with") !== "tdl-web") {
    return authError("csrf_header_missing", "Petición no autorizada.", 403);
  }
}

export function privateToken(request: NextRequest) {
  return getToken({ req: request, secret: process.env.AUTH_SECRET!, secureCookie: request.cookies.getAll().some((cookie) => cookie.name.startsWith("__Secure-authjs.session-token")) });
}

export function clearSession(request: NextRequest, response: NextResponse) {
  for (const cookie of request.cookies.getAll()) {
    if (/^(?:__Secure-)?authjs\.session-token(?:\.\d+)?$/.test(cookie.name)) {
      response.cookies.set(cookie.name, "", { maxAge: 0, path: "/", httpOnly: true, sameSite: "lax", secure: cookie.name.startsWith("__Secure-") });
    }
  }
  return response;
}

export async function withSession(request: NextRequest, forward: (request: NextAuthRequest) => Promise<Response>, restricted = false) {
  const csrf = checkCSRF(request);
  if (csrf) return csrf;
  const config = getAuthConfig();
  const { auth } = NextAuth({ ...config, callbacks: { ...config.callbacks,
    authorized: () => true,
    session: async ({ session, token }) => ({ ...session, accessToken: token.accessToken, error: token.error, mustChangePassword: token.mustChangePassword }),
  } });
  return await auth(async (req) => {
    if (req.auth?.error === "AuthUnavailable") return authError("auth_unavailable", "La autenticación no está disponible. Intenta de nuevo.", 503);
    if (!req.auth?.accessToken || req.auth.error) return authError("unauthorized", "Inicia sesión para continuar.", 401);
    if (req.auth.mustChangePassword && !restricted) return authError("password_change_required", "Cambia tu contraseña para continuar.", 403);
    return forward(req);
  })(request, {} as never) as Response;
}
