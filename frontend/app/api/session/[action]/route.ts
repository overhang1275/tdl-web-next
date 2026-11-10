import { NextResponse, type NextRequest } from "next/server";
import { AuthApiError, authRequest, logoutSession, recordActivity } from "@/lib/auth-api";
import { authError, checkCSRF, clearSession, privateToken, withSession } from "@/lib/auth-session";

export const runtime = "nodejs";
export async function POST(request: NextRequest, context: { params: Promise<{ action: string }> }) {
  const csrf = checkCSRF(request);
  if (csrf) return csrf;
  const { action } = await context.params;
  if (!["logout", "activity", "change-password", "refresh", "revoke-all"].includes(action)) return authError("not_found", "Ruta no disponible.", 404);
  if (action === "logout") {
    const token = await privateToken(request);
    try {
      if (token) await logoutSession(token.accessToken, token.refreshToken);
      return clearSession(request, new NextResponse(null, { status: 204 }));
    } catch { return authError("auth_unavailable", "No se pudo cerrar la sesión. Intenta de nuevo.", 503); }
  }
  return withSession(request, async (req) => {
    try {
      const access = req.auth!.accessToken!;
      if (action === "refresh") await authRequest("me", undefined, access, "GET");
      if (action === "activity") await recordActivity(access);
      if (action === "revoke-all") await authRequest("revoke-all", undefined, access);
      if (action === "change-password") {
        const body = await request.json().catch(() => null);
        if (!body || typeof body.current_password !== "string" || typeof body.new_password !== "string") return authError("invalid_password", "Revisa los campos de contraseña.", 422);
        await authRequest("change-password", { current_password: body.current_password, new_password: body.new_password }, access);
      }
      return new Response(null, { status: 204 });
    } catch (error) {
      return authError(error instanceof AuthApiError ? error.code : "auth_unavailable",
        error instanceof AuthApiError && error.status === 400 ? "La contraseña actual es incorrecta." : "No se pudo completar la petición. Revisa los datos e intenta de nuevo.",
        error instanceof AuthApiError ? error.status : 503);
    }
  }, action === "change-password");
}
