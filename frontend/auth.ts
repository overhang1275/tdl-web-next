import NextAuth, { type NextAuthConfig } from "next-auth";
import Authentik from "next-auth/providers/authentik";
import Credentials from "next-auth/providers/credentials";
import type { JWT } from "next-auth/jwt";

import { AuthApiError, exchangeAuthentik, loginLocal, logoutSession, refreshSession, type TokenPair } from "@/lib/auth-api";

const refreshes = new Map<string, Promise<JWT>>();
function withPair(token: JWT, pair: TokenPair): JWT {
  return { ...token, sub: pair.user.id, name: pair.user.name, email: pair.user.email, username: pair.user.username,
    accessToken: pair.access_token, refreshToken: pair.refresh_token, expiresAt: pair.expires_at,
    sessionId: pair.session_id, mustChangePassword: pair.must_change_password, error: undefined };
}

async function rotate(token: JWT): Promise<JWT> {
  try { return withPair(token, await refreshSession(String(token.refreshToken))); }
  catch (error) {
    if (error instanceof AuthApiError && error.status === 401) {
      return { ...token, accessToken: undefined, refreshToken: undefined, error: "RefreshTokenError" };
    }
    return { ...token, error: "AuthUnavailable" };
  }
}

export function authentikEnabled() {
  const enabled = (process.env.AUTHENTIK_ENABLED ?? "false").trim().toLowerCase();
  if (!["true", "false"].includes(enabled)) throw new Error("AUTHENTIK_ENABLED must be true or false");
  return enabled === "true";
}

export function getAuthConfig(): NextAuthConfig {
  const enabled = authentikEnabled();
  if (process.env.NODE_ENV === "production") {
    const required = ["AUTH_SECRET", "AUTH_URL", ...(enabled ? ["AUTHENTIK_ISSUER", "AUTHENTIK_CLIENT_ID", "AUTHENTIK_CLIENT_SECRET"] : [])];
    if (required.some((name) => !process.env[name])) throw new Error("Missing authentication configuration");
  }
  return {
    secret: process.env.AUTH_SECRET, trustHost: true,
    session: { strategy: "jwt", maxAge: 8 * 60 * 60 },
    pages: { signIn: "/login", error: "/login" },
    providers: [Credentials({
      credentials: { username: {}, password: { type: "password" } },
      async authorize(credentials) {
        if (typeof credentials.username !== "string" || typeof credentials.password !== "string") return null;
        try {
          const pair = await loginLocal(credentials.username, credentials.password);
          return { id: pair.user.id, name: pair.user.name, email: pair.user.email, pair };
        } catch { return null; }
      },
    }), ...(enabled ? [Authentik({
      clientId: process.env.AUTHENTIK_CLIENT_ID ?? "", clientSecret: process.env.AUTHENTIK_CLIENT_SECRET ?? "",
      issuer: process.env.AUTHENTIK_ISSUER, checks: ["pkce", "state"],
      authorization: { params: { scope: "openid profile email" } },
    })] : [])],
    callbacks: {
      async jwt({ token, account, user }) {
        if (user?.pair) return withPair(token, user.pair);
        if (account?.provider === "authentik") {
          if (!account.access_token) return null;
          return withPair(token, await exchangeAuthentik(account.access_token));
        }
        if (token.mustChangePassword) return token;
        if (token.expiresAt && Date.now() < (token.expiresAt - 60) * 1000) return { ...token, error: undefined };
        if (!token.refreshToken) return { ...token, accessToken: undefined, error: "RefreshTokenError" };
        const key = token.refreshToken;
        if (!refreshes.has(key)) {
          const pending = rotate(token);
          refreshes.set(key, pending);
          void pending.finally(() => setTimeout(() => refreshes.delete(key), 5_000).unref());
        }
        return refreshes.get(key)!;
      },
      async session({ session, token }) {
        return { expires: session.expires, user: { name: token.name, email: token.email, username: token.username,
          groups: [], mustChangePassword: token.mustChangePassword }, error: token.error };
      },
      async redirect({ url, baseUrl }) {
        try {
          const target = new URL(url, baseUrl);
          if (target.origin === new URL(baseUrl).origin) return target.href;
        } catch {}
        return baseUrl;
      },
    },
    events: { async signOut(message) { if ("token" in message && message.token) await logoutSession(message.token.accessToken, message.token.refreshToken); } },
    logger: { error() { /* Authentication errors must never serialize credentials or provider payloads. */ } },
  };
}

export const { handlers, auth } = NextAuth(getAuthConfig);
