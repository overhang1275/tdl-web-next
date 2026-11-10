import "next-auth";
import "next-auth/jwt";

declare module "next-auth" {
  interface Session {
    user: {
      name?: string | null;
      email?: string | null;
      image?: string | null;
      groups?: string[];
      username?: string;
      mustChangePassword?: boolean;
    };
    error?: string;
    /** Populated only by the private BFF session callback. */
    accessToken?: string;
    mustChangePassword?: boolean;
  }

  interface User {
    groups?: string[];
    pair?: import("@/lib/auth-api").TokenPair;
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    accessToken?: string;
    refreshToken?: string;
    expiresAt?: number;
    groups?: string[];
    error?: string;
    username?: string;
    sessionId?: string;
    mustChangePassword?: boolean;
  }
}
