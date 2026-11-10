"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Button, Card, Input, Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui";
import { ErrorState, LoadingRows, PageHeader, ConfirmDialog } from "@/components/states";
import { apiFetch, ApiError } from "@/lib/api";

type ManagedUser = { id: string; username: string; display_name: string | null; active: boolean; must_change_password: boolean; is_local: boolean };
export default function UsersPage() {
  const client = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: () => apiFetch<ManagedUser[]>("/api/v1/users") });
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [reset, setReset] = useState<ManagedUser | null>(null);
  const [confirm, setConfirm] = useState<{ user: ManagedUser; action: "disable" | "revoke" } | null>(null);
  async function save(path: string, method: string, body?: unknown) {
    setBusy(true); setError(""); setMessage("");
    try {
      await apiFetch(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });
      await client.invalidateQueries({ queryKey: ["users"] });
      setMessage("Cambios guardados."); setReset(null); setConfirm(null);
      return true;
    } catch (failure) {
      setConfirm(null);
      setError(failure instanceof ApiError && failure.code === "last_local_admin" ? "Debe quedar al menos un administrador local activo." : failure instanceof Error ? failure.message : "No se pudo guardar. Intenta de nuevo.");
      return false;
    } finally { setBusy(false); }
  }
  return <div className="space-y-6">
    <PageHeader title="Usuarios" description="Todas las cuentas activas tienen acceso de administrador." />
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {message && <p role="status" className="text-sm">{message}</p>}
    <Card className="p-5"><h2 className="text-base font-semibold">Crear cuenta local</h2><p className="mt-1 text-sm text-muted-foreground">La contraseña inicial deberá cambiarse al entrar.</p>
      <form method="post" className="mt-4 grid gap-4 sm:grid-cols-2" aria-busy={busy} onSubmit={async (event) => {
        event.preventDefault(); const form = event.currentTarget; const data = new FormData(form);
        if (await save("/api/v1/users", "POST", { username: data.get("username"), display_name: data.get("display_name") || null, password: data.get("password") })) form.reset();
      }}>
        <div><label htmlFor="create-username" className="text-sm">Usuario</label><Input id="create-username" name="username" autoComplete="off" required className="mt-1" /></div>
        <div><label htmlFor="create-name" className="text-sm">Nombre visible</label><Input id="create-name" name="display_name" autoComplete="off" className="mt-1" /></div>
        <div><label htmlFor="create-password" className="text-sm">Contraseña temporal</label><Input id="create-password" name="password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required className="mt-1" /></div>
        <div className="self-end"><Button disabled={busy} type="submit">Crear usuario</Button></div>
      </form>
    </Card>
    {users.isLoading ? <LoadingRows /> : users.isError ? <ErrorState description={users.error.message} onRetry={() => users.refetch()} /> :
      <div className="grid gap-4">{users.data?.map((user) => <Card className="p-5" key={user.id}>
        <h2 className="font-semibold">{user.username}</h2><p className="mt-1 text-sm text-muted-foreground">{user.active ? "Activo" : "Desactivado"} · {user.is_local ? "Cuenta local" : "Authentik"}{user.must_change_password ? " · Contraseña temporal" : ""}</p>
        <form className="mt-4 flex flex-wrap items-end gap-3" onSubmit={(event) => { event.preventDefault(); const data = new FormData(event.currentTarget); void save(`/api/v1/users/${user.id}`, "PATCH", { display_name: data.get("display_name") || null }); }}>
          <div className="min-w-0 flex-1"><label htmlFor={`name-${user.id}`} className="text-sm">Nombre visible de {user.username}</label><Input id={`name-${user.id}`} name="display_name" defaultValue={user.display_name ?? ""} className="mt-1" /></div><Button variant="outline" type="submit" disabled={busy}>Guardar nombre</Button>
        </form>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="outline" disabled={busy} onClick={() => user.active ? setConfirm({ user, action: "disable" }) : void save(`/api/v1/users/${user.id}`, "PATCH", { active: true })}>{user.active ? "Desactivar" : "Activar"}</Button>
          <Button variant="outline" disabled={busy} onClick={() => setConfirm({ user, action: "revoke" })}>Revocar sesiones</Button>
          {user.is_local && <Button variant="outline" disabled={busy} onClick={() => setReset(user)}>Restablecer contraseña</Button>}
        </div>
      </Card>)}</div>}
    <ConfirmDialog open={!!confirm} onOpenChange={(open) => { if (!open) setConfirm(null); }} title={confirm?.action === "disable" ? "Desactivar cuenta" : "Revocar sesiones"} description={`Se cerrarán las sesiones de ${confirm?.user.username ?? "esta cuenta"}.`} danger busy={busy} onConfirm={() => { if (confirm) void save(`/api/v1/users/${confirm.user.id}${confirm.action === "revoke" ? "/revoke-sessions" : ""}`, confirm.action === "revoke" ? "POST" : "PATCH", confirm.action === "revoke" ? undefined : { active: false }); }} />
    <Dialog open={!!reset} onOpenChange={(open) => { if (!open) setReset(null); }}><DialogContent><DialogTitle>Restablecer contraseña</DialogTitle><DialogDescription>La cuenta deberá cambiar esta contraseña temporal. Se cerrarán todas sus sesiones.</DialogDescription>
      <form className="mt-4 space-y-4" onSubmit={(event) => { event.preventDefault(); if (reset) void save(`/api/v1/users/${reset.id}/reset-password`, "POST", { password: new FormData(event.currentTarget).get("password") }); }}><label htmlFor="reset-password" className="text-sm">Nueva contraseña temporal</label><Input id="reset-password" name="password" type="password" autoComplete="new-password" minLength={12} maxLength={128} required />{error && <p role="alert" className="text-sm text-destructive">{error}</p>}<Button type="submit" disabled={busy}>Restablecer</Button></form>
    </DialogContent></Dialog>
  </div>;
}
