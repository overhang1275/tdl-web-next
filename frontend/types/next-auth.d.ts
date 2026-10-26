import "next-auth";
import "next-auth/jwt";

declare module "next-auth" {
  interface Session {
    user: {
      name?: string | null;
      email?: string | null;
      image?: string | null;
      groups?: string[];
    };
    error?: string;
    /** Populated only by the private BFF session callback. */
    accessToken?: string;
  }

  interface User {
    groups?: string[];
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    accessToken?: string;
    refreshToken?: string;
    expiresAt?: number;
    groups?: string[];
    error?: string;
  }
}
