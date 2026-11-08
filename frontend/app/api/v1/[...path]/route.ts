import type { NextAuthRequest } from "next-auth";
import type { NextRequest } from "next/server";

import { withSession } from "@/lib/auth-session";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const API_URL = process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000";

function error(code: string, message: string, status: number) {
  return Response.json({ error: { code, message, detail: null } }, { status });
}

// Auth.js refreshes the JWT and writes its encrypted cookie; this session is server-only.
async function proxy(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  if (path.some((part) => !part || /[%/\\]/.test(part) || part === "." || part === "..") ||
      (path[0]?.toLowerCase() === "auth" && path[1] !== "me")) {
    return error("not_found", "Ruta no disponible.", 404);
  }
  return withSession(request, (req) => forward(req, context));
}

async function forward(request: NextAuthRequest, context: { params: Promise<{ path: string[] }> }) {
  if (!request.auth?.accessToken || request.auth.error) {
    return error("unauthorized", "Inicia sesión para continuar.", 401);
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
