"use client";
import { useState, useSyncExternalStore, type FormEvent } from "react";
import { signIn } from "next-auth/react";
import { Button, Input } from "@/components/ui";
import { apiFetch } from "@/lib/api";

const subscribe = () => () => {};
function useHydrated() { return useSyncExternalStore(subscribe, () => true, () => false); }

export function LoginForm({ external }: { external: boolean }) {
  const ready = useHydrated();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setPending(true); setError("");
    const data = new FormData(event.currentTarget);
    try {
      const result = await signIn("credentials", { username: data.get("username"), password: data.get("password"), redirect: false });
      if (result?.error) { setError("No se pudo iniciar sesión. Revisa tu usuario y contraseña e intenta de nuevo."); setPending(false); }
      // Reload to discard private-route and query caches from the previous identity.
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      else window.location.assign("/");
    } catch { setError("El servicio no está disponible. Intenta de nuevo."); setPending(false); }
  }
  return <div className="mt-8 space-y-4">
    <form method="post" onSubmit={submit} className="space-y-4" aria-busy={pending}>
      <div><label htmlFor="username" className="text-sm font-medium">Usuario</label><Input id="username" name="username" autoComplete="username" required className="mt-1" disabled={pending} /></div>
      <div><label htmlFor="password" className="text-sm font-medium">Contraseña</label><Input id="password" name="password" type="password" autoComplete="current-password" required className="mt-1" disabled={pending} aria-describedby={error ? "login-error" : undefined} /></div>
      {error && <p id="login-error" role="alert" className="text-sm text-destructive">{error}</p>}
      <Button type="submit" size="lg" className="w-full" disabled={pending || !ready}>{pending ? "Iniciando sesión…" : "Iniciar sesión"}</Button>
    </form>
    {external && <Button variant="outline" className="w-full" disabled={pending || !ready} aria-describedby={error ? "login-error" : undefined} onClick={async () => {
      setPending(true); setError("");
      try { await signIn("authentik", { redirectTo: "/" }); }
      catch { setError("No se pudo conectar con Authentik. Intenta de nuevo."); setPending(false); }
    }}>Continuar con Authentik</Button>}
  </div>;
}

export function LogoutButton() {
  const ready = useHydrated();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  return <><Button type="button" variant="ghost" className="mt-3 w-full" disabled={pending || !ready} onClick={async () => {
    setPending(true); setError("");
    try { await apiFetch("/api/session/logout", { method: "POST" });
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/login"); }
    catch { setError("No se pudo cerrar la sesión. Intenta de nuevo."); setPending(false); }
  }}>{pending ? "Cerrando sesión…" : "Cerrar sesión"}</Button>{error && <p role="alert" className="text-sm text-destructive">{error}</p>}</>;
}

export function PasswordForm() {
  const ready = useHydrated();
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  return <form method="post" className="mt-6 space-y-4" aria-busy={pending} onSubmit={async (event) => {
    event.preventDefault(); setPending(true); setError("");
    const data = new FormData(event.currentTarget);
    try {
      await apiFetch("/api/session/change-password", { method: "POST", body: JSON.stringify({ current_password: data.get("current_password"), new_password: data.get("new_password") }) });
      await apiFetch("/api/session/logout", { method: "POST" });
      // eslint-disable-next-line @next/next/no-location-assign-relative-destination
      window.location.assign("/login?changed=1");
    } catch (failure) { setError(failure instanceof Error ? failure.message : "No se pudo cambiar la contraseña."); setPending(false); }
  }}>
    <div><label htmlFor="current-password" className="text-sm font-medium">Contraseña actual</label><Input id="current-password" name="current_password" type="password" autoComplete="current-password" required className="mt-1" /></div>
    <div><label htmlFor="new-password" className="text-sm font-medium">Nueva contraseña</label><Input id="new-password" name="new_password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required className="mt-1" aria-describedby="password-help" /><p id="password-help" className="mt-1 text-xs text-muted-foreground">De 12 a 128 caracteres. Se cerrarán todas tus sesiones.</p></div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <Button type="submit" disabled={pending || !ready}>{pending ? "Guardando…" : "Cambiar contraseña"}</Button>
    <LogoutButton />
  </form>;
}
