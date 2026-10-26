"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LogIn, RotateCcw, Send, Square } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import {
  ConfirmDialog,
  ErrorState,
  LoadingRows,
  PageHeader,
  StatusBadge,
} from "@/components/states";
import { Button, Card, Input } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Status } from "@/lib/types";

interface SettingsData {
  app: { name: string; version: string; environment: string };
  paths: Record<string, string>;
  limits: Record<string, number>;
  tdl: { binary: string; namespace: string };
  authentik: { issuer: string; audience: string; admin_group: string };
  can_start_services: boolean;
}

interface Me {
  username: string;
  email: string | null;
  name: string | null;
  groups: string[];
  expires_at: string | null;
}

interface LoginStatus {
  running: boolean;
  output: string[];
  returncode: number | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const [value, setValue] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [keepSession, setKeepSession] = useState(true);
  const [resetOpen, setResetOpen] = useState(false);
  const settings = useQuery({
    queryKey: queryKeys.settings,
    queryFn: () => apiFetch<SettingsData>("/api/v1/settings"),
  });
  const status = useQuery({
    queryKey: queryKeys.status,
    queryFn: () => apiFetch<Status>("/api/v1/status"),
  });
  const me = useQuery({
    queryKey: ["me"],
    queryFn: () => apiFetch<Me>("/api/v1/auth/me"),
  });
  const login = useQuery({
    queryKey: ["telegram-login"],
    queryFn: () => apiFetch<LoginStatus>("/api/v1/telegram/login"),
    refetchInterval: (query) => (query.state.data?.running ? 1_500 : false),
  });
  const start = useMutation({
    mutationFn: () =>
      apiFetch<LoginStatus>("/api/v1/telegram/login/start", { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["telegram-login"] }),
    onError: (error) => toast.error(error.message),
  });
  const send = useMutation({
    mutationFn: () =>
      apiFetch<LoginStatus>("/api/v1/telegram/login/input", {
        method: "POST",
        body: JSON.stringify({ value }),
      }),
    onSuccess: () => {
      setValue("");
      queryClient.invalidateQueries({ queryKey: ["telegram-login"] });
    },
    onError: (error) => toast.error(error.message),
  });
  const cancel = useMutation({
    mutationFn: () =>
      apiFetch<LoginStatus>("/api/v1/telegram/login/cancel", { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["telegram-login"] }),
  });
  const reset = useMutation({
    mutationFn: () =>
      apiFetch<Record<string, unknown>>("/api/v1/admin/reset", {
        method: "POST",
        body: JSON.stringify({ confirmation, keep_session: keepSession }),
      }),
    onSuccess: () => {
      toast.success("Reinicio completado");
      setResetOpen(false);
      setConfirmation("");
      queryClient.clear();
    },
    onError: (error) => toast.error(error.message),
  });

  if (settings.isError) {
    return (
      <>
        <PageHeader title="Configuración" />
        <ErrorState description={settings.error.message} onRetry={() => settings.refetch()} />
      </>
    );
  }
  if (settings.isLoading || !settings.data) {
    return (
      <>
        <PageHeader title="Configuración" />
        <LoadingRows rows={4} />
      </>
    );
  }
  const data = settings.data;
  return (
    <>
      <PageHeader
        title="Configuración"
        description="Estado, rutas y sesión. Los valores son de solo lectura."
      />

      <div className="grid gap-4 xl:grid-cols-2">
        <Card className="p-5">
          <h2 className="font-semibold">Sistema</h2>
          <dl className="mt-3 space-y-2 text-sm">
            <Row label="Aplicación" value={`${data.app.name} ${data.app.version}`} />
            <Row label="Entorno" value={data.app.environment} />
            <Row label="Usuario" value={me.data?.name ?? me.data?.username ?? "—"} />
            <Row label="Email" value={me.data?.email ?? "—"} />
            <Row label="Grupos" value={me.data?.groups.join(", ") || "—"} />
            <Row label="Sesión expira" value={formatDate(me.data?.expires_at)} />
          </dl>
          <div className="mt-3 flex flex-wrap gap-4 text-xs text-muted-foreground">
            <span className="inline-flex items-center gap-2">
              tdl <StatusBadge status={status.data?.tdl_installed ? "completed" : "failed"} />
            </span>
            <span className="inline-flex items-center gap-2">
              Redis <StatusBadge status={status.data?.redis_connected ? "completed" : "failed"} />
            </span>
            <span className="inline-flex items-center gap-2">
              Worker <StatusBadge status={status.data?.worker_connected ? "completed" : "failed"} />
            </span>
            <span className="inline-flex items-center gap-2">
              Telegram <StatusBadge status={status.data?.session_active ? "completed" : "pending"} />
            </span>
          </div>
        </Card>

        <Card className="p-5">
          <h2 className="font-semibold">Rutas y límites</h2>
          <dl className="mt-3 space-y-2 text-sm">
            {Object.entries(data.paths).map(([key, value]) => (
              <Row key={key} label={key} value={value} mono />
            ))}
            {Object.entries(data.limits).map(([key, value]) => (
              <Row key={key} label={key} value={String(value)} />
            ))}
            <Row label="tdl" value={`${data.tdl.binary} · ns ${data.tdl.namespace}`} mono />
            <Row label="Authentik issuer" value={data.authentik.issuer || "—"} mono />
            <Row
              label="Grupo admin"
              value={data.authentik.admin_group || "definido en Authentik"}
            />
          </dl>
        </Card>
      </div>

      <Card className="mt-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="font-semibold">Login de Telegram</h2>
            <p className="text-xs text-muted-foreground">
              Responde los prompts de tdl: teléfono, código y 2FA si aplica.
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              onClick={() => start.mutate()}
              disabled={start.isPending || login.data?.running}
            >
              <LogIn className="h-4 w-4" />
              Iniciar login
            </Button>
            {login.data?.running ? (
              <Button variant="outline" onClick={() => cancel.mutate()}>
                <Square className="h-4 w-4" />
                Cancelar
              </Button>
            ) : null}
          </div>
        </div>
        <pre className="mt-3 max-h-64 overflow-auto rounded-lg border border-border bg-slate-950 p-4 text-xs leading-5 text-slate-200">
          {login.data?.output.length
            ? login.data.output.join("")
            : "Login no iniciado."}
        </pre>
        {login.data?.running ? (
          <form
            className="mt-3 flex gap-2"
            onSubmit={(event) => {
              event.preventDefault();
              if (value.trim()) send.mutate();
            }}
          >
            <Input
              value={value}
              onChange={(event) => setValue(event.target.value)}
              placeholder="Teléfono, código o contraseña 2FA"
              autoComplete="one-time-code"
              type="password"
            />
            <Button type="submit" disabled={send.isPending || !value.trim()}>
              <Send className="h-4 w-4" />
              Enviar
            </Button>
          </form>
        ) : null}
        {login.data?.finished_at ? (
          <p className="mt-2 text-xs text-muted-foreground">
            Proceso terminado con código {login.data.returncode ?? "—"}.
          </p>
        ) : null}
      </Card>

      <Card className="mt-4 border-destructive/30 p-5">
        <h2 className="font-semibold text-destructive">Zona de peligro</h2>
        <p className="text-xs text-muted-foreground">
          Borra jobs, plantillas, exports, descargas, logs y el caché de chats. Conserva la
          base y los backups. Escribe REINICIAR para confirmar.
        </p>
        <div className="mt-3 flex flex-col gap-2 sm:flex-row sm:items-center">
          <Input
            value={confirmation}
            onChange={(event) => setConfirmation(event.target.value)}
            placeholder="REINICIAR"
            className="sm:max-w-48"
          />
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={keepSession}
              onChange={(event) => setKeepSession(event.target.checked)}
            />
            Conservar sesión de Telegram
          </label>
          <Button
            variant="danger"
            onClick={() => setResetOpen(true)}
            disabled={confirmation.trim() !== "REINICIAR"}
          >
            <RotateCcw className="h-4 w-4" />
            Reiniciar
          </Button>
        </div>
      </Card>

      <ConfirmDialog
        open={resetOpen}
        onOpenChange={setResetOpen}
        title="Reiniciar la aplicación"
        description="Se borrarán jobs, plantillas, exports, descargas y logs. Esta acción no se puede deshacer."
        confirmLabel="Reiniciar"
        danger
        busy={reset.isPending}
        onConfirm={() => reset.mutate()}
      />
    </>
  );
}

function Row({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className={mono ? "mono max-w-[60%] break-all text-right text-xs" : "max-w-[60%] break-words text-right"}>
        {value}
      </dd>
    </div>
  );
}
