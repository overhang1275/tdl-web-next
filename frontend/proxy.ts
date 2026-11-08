import { NextResponse, type NextRequest } from "next/server";
import { authRequest, AuthApiError, type Identity } from "@/lib/auth-api";
import { appURL, privateToken } from "@/lib/auth-session";

export default async function proxy(request: NextRequest) {
  const url = appURL(request);
  const login = new URL("/login", url);
  login.searchParams.set("callbackUrl", url.href);
  const token = await privateToken(request);
  if (!token?.accessToken) return NextResponse.redirect(login);
  try {
    const user = await authRequest<Identity>("me", undefined, token.accessToken, "GET");
    if (user.must_change_password && url.pathname !== "/change-password") return NextResponse.redirect(new URL("/change-password", url));
    return NextResponse.next();
  } catch (error) {
    if (error instanceof AuthApiError && error.status === 401) {
      // A writable endpoint rotates cookies before retrying the original navigation.
      if (token.refreshToken && !token.mustChangePassword) {
        const refresh = new URL("/session/refresh", url);
        refresh.searchParams.set("returnTo", url.pathname + url.search);
        return NextResponse.redirect(refresh);
      }
      return NextResponse.redirect(login);
    }
    return new NextResponse("La autenticación no está disponible. Recarga la página para intentar de nuevo.", { status: 503, headers: { "content-type": "text/plain; charset=utf-8", "cache-control": "no-store" } });
  }
}

export const config = { matcher: ["/((?!api/|login|session/refresh|signed-out|_next/static|_next/image|favicon.ico|health|robots.txt).*)"] };
