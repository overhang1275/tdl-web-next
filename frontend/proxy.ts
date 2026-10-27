import { auth } from "@/auth";
import type { NextAuthRequest } from "next-auth";
import { NextResponse, type NextFetchEvent, type NextMiddleware, type NextRequest } from "next/server";

export default async function proxy(request: NextRequest, event: NextFetchEvent) {
  const check: (authenticated: NextAuthRequest, event: NextFetchEvent) => ReturnType<NextMiddleware> = (authenticated) => {
    if (authenticated.auth?.user && !authenticated.auth.error) return NextResponse.next();
    // Auth.js may rewrite its request origin using AUTH_URL; keep this redirect on TDL.
    const incoming = new URL(request.url);
    const host = request.headers.get("host");
    if (host) {
      incoming.port = "";
      incoming.host = host;
    }
    const login = new URL("/login", incoming);
    login.searchParams.set("callbackUrl", incoming.href);
    return NextResponse.redirect(login);
  };
  const authenticate = await auth(check);
  return authenticate(request, event);
}

export const config = {
  matcher: [
    "/((?!api/|login|_next/static|_next/image|favicon.ico|health|robots.txt).*)",
  ],
};
