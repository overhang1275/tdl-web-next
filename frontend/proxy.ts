import { auth } from "@/auth";

export default auth;

export const config = {
  matcher: [
    "/((?!api/|login|_next/static|_next/image|favicon.ico|health|robots.txt).*)",
  ],
};
