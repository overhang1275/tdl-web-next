import "server-only";

export type Identity = { id: string; username: string; name: string; email?: string | null; groups: string[]; must_change_password?: boolean };
export type TokenPair = { access_token: string; refresh_token: string; expires_at: number; session_id: string; must_change_password: boolean; user: Identity };

export class AuthApiError extends Error {
  constructor(public status: number, public code: string) {
    super(status === 401 ? "Usuario o contraseña incorrectos." : "No se pudo completar la autenticación. Intenta de nuevo.");
  }
}

export async function authRequest<T>(path: string, body?: unknown, accessToken?: string, method = "POST"): Promise<T> {
  let response: Response;
  try {
    response = await fetch(new URL(`/api/v1/auth/${path}`, process.env.API_INTERNAL_URL ?? "http://127.0.0.1:8000"), {
      method, cache: "no-store", signal: AbortSignal.timeout(10_000),
      headers: { "content-type": "application/json", "x-requested-with": "tdl-web", ...(accessToken ? { authorization: `Bearer ${accessToken}` } : {}) },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch { throw new AuthApiError(503, "auth_unavailable"); }
  if (!response.ok) {
    const data = await response.json().catch(() => null);
    throw new AuthApiError(response.status, typeof data?.error?.code === "string" ? data.error.code : "auth_unavailable");
  }
  return response.status === 204 ? undefined as T : await response.json() as T;
}

export const loginLocal = (username: string, password: string) => authRequest<TokenPair>("token", { username, password });
export const exchangeAuthentik = (access_token: string) => authRequest<TokenPair>("exchange", { access_token });
export const refreshSession = (refresh_token: string) => authRequest<TokenPair>("refresh", { refresh_token });
export const recordActivity = (accessToken: string) => authRequest<void>("activity", undefined, accessToken);
export async function logoutSession(accessToken?: string, refreshToken?: string) {
  try {
    await authRequest<void>("logout", refreshToken ? { refresh_token: refreshToken } : undefined, refreshToken ? undefined : accessToken);
  } catch (error) {
    if (!(error instanceof AuthApiError && error.status === 401)) throw error;
  }
}
