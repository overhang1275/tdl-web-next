import NextAuth, { type NextAuthConfig } from "next-auth";
import Authentik from "next-auth/providers/authentik";
import type { JWT } from "next-auth/jwt";

const issuer = process.env.AUTHENTIK_ISSUER ?? "";
const tokenUrl =
  process.env.AUTHENTIK_TOKEN_URL ?? (issuer ? new URL("/application/o/token/", issuer).href : "");

const refreshes = new Map<string, Promise<JWT>>();

function refreshAccessToken(token: JWT): Promise<JWT> {
  const key = String(token.refreshToken);
  const pending = refreshes.get(key);
  if (pending) return pending;
  const result = rotateAccessToken(token);
  refreshes.set(key, result);
  // One web process: let concurrent requests using the old cookie share the rotation.
  void result.finally(() => setTimeout(() => refreshes.delete(key), 5_000).unref());
  return result;
}

async function rotateAccessToken(token: JWT): Promise<JWT> {
  try {
    const response = await fetch(tokenUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        grant_type: "refresh_token",
        client_id: process.env.AUTHENTIK_CLIENT_ID ?? "",
        client_secret: process.env.AUTHENTIK_CLIENT_SECRET ?? "",
        refresh_token: String(token.refreshToken ?? ""),
      }),
      cache: "no-store",
      signal: AbortSignal.timeout(10_000),
    });
    const data = (await response.json()) as {
      access_token?: string;
      refresh_token?: string;
      expires_in?: number;
      error?: string;
    };
    if (!response.ok || !data.access_token) {
      throw new Error(data.error ?? "refresh_failed");
    }
    return {
      ...token,
      accessToken: data.access_token,
      refreshToken: data.refresh_token ?? token.refreshToken,
      expiresAt: Math.floor(Date.now() / 1000) + Number(data.expires_in ?? 300),
      error: undefined,
    };
  } catch {
    return { ...token, accessToken: undefined, refreshToken: undefined, error: "RefreshTokenError" };
  }
}

const config: NextAuthConfig = {
  secret: process.env.AUTH_SECRET,
  trustHost: true,
  session: { strategy: "jwt", maxAge: 8 * 60 * 60 },
  pages: { signIn: "/login" },
  providers: [
    Authentik({
      clientId: process.env.AUTHENTIK_CLIENT_ID ?? "",
      clientSecret: process.env.AUTHENTIK_CLIENT_SECRET ?? "",
      issuer,
      checks: ["pkce", "state"],
      authorization: { params: { scope: "openid profile email offline_access tdl-groups" } },
    }),
  ],
  callbacks: {
    authorized({ auth }) {
      return Boolean(auth?.user && !auth.error);
    },
    async signIn({ profile }) {
      const group = process.env.AUTHENTIK_ADMIN_GROUP;
      return !group || (Array.isArray(profile?.groups) && profile.groups.includes(group));
    },
    async jwt({ token, account, profile }) {
      if (account) {
        token.accessToken = account.access_token;
        token.refreshToken = account.refresh_token;
        token.expiresAt = account.expires_at;
        token.groups = Array.isArray(profile?.groups)
          ? profile.groups.filter((group): group is string => typeof group === "string")
          : [];
      }
      if (token.error) return token;
      if (token.expiresAt && Date.now() < (Number(token.expiresAt) - 60) * 1000) {
        return token;
      }
      if (token.refreshToken) {
        return refreshAccessToken(token);
      }
      return { ...token, accessToken: undefined, error: "RefreshTokenError" };
    },
    async session({ session, token }) {
      session.user.groups = token.groups ?? [];
      session.error = token.error;
      return session;
    },
  },
};

export function getAuthConfig(): NextAuthConfig {
  if (process.env.NODE_ENV === "production") {
    const required = ["AUTH_SECRET", "AUTH_URL", "AUTHENTIK_ISSUER", "AUTHENTIK_CLIENT_ID", "AUTHENTIK_CLIENT_SECRET"];
    const missing = required.filter((name) => !process.env[name]);
    if (missing.length) throw new Error(`Missing authentication configuration: ${missing.join(", ")}`);
  }
  return config;
}

export const { handlers, auth, signIn, signOut } = NextAuth(getAuthConfig);
