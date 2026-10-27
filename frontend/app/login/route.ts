import { NextRequest, NextResponse } from "next/server";
import { auth, signIn } from "@/auth";

export async function GET(request: NextRequest) {
  const origin = new URL(process.env.AUTH_URL ?? request.url).origin;
  if (request.nextUrl.searchParams.has("error")) {
    return NextResponse.redirect(new URL("/signed-out?error=authentication", origin));
  }
  let redirectTo = new URL("/", origin);
  try {
    const target = new URL(request.nextUrl.searchParams.get("callbackUrl") ?? "/", origin);
    if (target.origin === origin) redirectTo = target;
  } catch {
    // Invalid return URLs must not turn the login endpoint into an open redirect.
  }
  const session = await auth();
  if (session?.user && !session.error) {
    return NextResponse.redirect(redirectTo);
  }
  const destination = await signIn("authentik", { redirect: false, redirectTo: redirectTo.href });
  return NextResponse.redirect(destination);
}
