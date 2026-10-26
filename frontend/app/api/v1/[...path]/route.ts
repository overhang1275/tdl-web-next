import NextAuth, { type NextAuthRequest } from "next-auth";
import type { NextRequest } from "next/server";

import { getAuthConfig } from "@/auth";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API_URL = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";

function error(code: string, message: string, status: number) {
  return Response.json({ error: { code, message, detail: null } }, { status });
}

// Auth.js refreshes the JWT and writes its encrypted cookie; this session is server-only.
async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const config = getAuthConfig();
  const { auth: apiAuth } = NextAuth({
    ...config,
    callbacks: {
      ...config.callbacks,
      authorized: () => true,
      session: async ({ session, token }) => ({ ...session, accessToken: token.accessToken, error: token.error }),
    },
  });
  return (await apiAuth(forward)(request, context)) ?? error("auth_failed", "Inicia sesión para continuar.", 401);
}

async function forward(request: NextAuthRequest, context: { params: Promise<{ path: string[] }> }) {
  if (!request.auth?.accessToken || request.auth.error) {
    return error("unauthorized", "Inicia sesión para continuar.", 401);
  }
  const origin = request.headers.get("origin");
  if (origin) {
    try {
      if (new URL(origin).origin !== new URL(process.env.AUTH_URL ?? request.url).origin) {
        return error("cross_origin_blocked", "Origen no permitido.", 403);
      }
    } catch {
      return error("cross_origin_blocked", "Origen no permitido.", 403);
    }
  }
  const method = request.method.toUpperCase();
  if (!["GET", "HEAD"].includes(method)) {
    if (request.headers.get("x-requested-with") !== "tdl-web") {
      return error("csrf_header_missing", "Petición no autorizada.", 403);
    }
  }
  const { path } = await context.params;
  const target = new URL(`/api/v1/${path.map(encodeURIComponent).join("/")}`, API_URL);
  target.search = request.nextUrl.search;
  const headers = new Headers();
  for (const name of ["content-type", "accept", "accept-language", "range", "idempotency-key"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  headers.set("authorization", `Bearer ${request.auth.accessToken}`);
  headers.set("x-requested-with", "tdl-web");
  const init: RequestInit & { duplex?: "half" } = {
    method,
    headers,
    redirect: "manual",
    cache: "no-store",
    signal: request.signal,
    body: ["GET", "HEAD"].includes(method) ? undefined : request.body,
    duplex: "half",
  };
  let upstream: Response;
  try {
    upstream = await fetch(target, init);
  } catch {
    return error("upstream_unavailable", "La API no está disponible.", 502);
  }
  const responseHeaders = new Headers();
  for (const name of [
    "content-type",
    "content-length",
    "content-disposition",
    "content-range",
    "accept-ranges",
    "content-security-policy",
    "cache-control",
  ]) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  responseHeaders.set("x-content-type-options", "nosniff");
  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export {
  proxy as GET,
  proxy as HEAD,
  proxy as POST,
  proxy as PUT,
  proxy as PATCH,
  proxy as DELETE,
};
