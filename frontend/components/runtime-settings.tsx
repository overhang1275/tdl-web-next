"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";

import { ConfirmDialog } from "@/components/states";
import { Button, Card, Input } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";

export interface RuntimeSettingsData {
  paths: Record<string, string>;
  limits: Record<string, number>;
  downloads_storage_root?: string;
  operation?: {
    id: string | null;
    status: string;
    error: string | null;
    source: string | null;
    destination: string | null;
  };
}

type Values = { downloads_dir: string } & Record<string, string | number | boolean>;

const limits = [
  { name: "command_timeout_seconds", label: "Tiempo máximo por comando", unit: "segundos", max: 86400 },
  { name: "download_batch_size", label: "Archivos por lote de descarga", unit: "archivos", max: 10000 },
  { name: "download_idle_timeout_seconds", label: "Espera máxima sin progreso", unit: "segundos", max: 86400 },
  { name: "export_batch_size", label: "Mensajes por lote de exportación", unit: "mensajes", max: 100000 },
];

export function RuntimeSettingsForm({ data }: { data: RuntimeSettingsData }) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState<Values | null>(null);
  const operation = data.operation;
  const busy = ["queued", "moving", "failed"].includes(operation?.status ?? "idle");
  const refresh = () => {
    queryClient.invalidateQueries({ queryKey: queryKeys.settings });
    queryClient.invalidateQueries({ queryKey: queryKeys.dashboard });
  };
  const save = useMutation({
    mutationFn: (values: Values) => apiFetch<RuntimeSettingsData>("/api/v1/settings", {
      method: "PUT", body: JSON.stringify(values),
    }),
    onSuccess: (result) => {
      setPending(null);
      queryClient.setQueryData(queryKeys.settings, result);
      toast.success(result.operation?.status === "queued" ? "Traslado en cola" : "Ajustes guardados");
      refresh();
    },
    onError: () => { setPending(null); refresh(); },
  });
  const retry = useMutation({
    mutationFn: () => apiFetch<RuntimeSettingsData>("/api/v1/settings/retry", { method: "POST" }),
    onSuccess: () => { save.reset(); toast.success("Recuperación en cola"); refresh(); },
    onError: refresh,
  });
  const error = save.error ?? retry.error;
  const formKey = JSON.stringify([data.paths.downloads_dir, ...limits.map(({ name }) => data.limits[name])]);

  return (
    <Card className="mt-4 p-5">
      <h2 className="font-semibold">Descargas y rendimiento</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Los cambios se conservan al reiniciar. Guarda cuando no haya descargas ni borrados pendientes.
      </p>
      <form key={formKey} autoComplete="off" aria-busy={save.isPending} className="mt-4 space-y-4" onSubmit={(event) => {
        event.preventDefault();
        const form = new FormData(event.currentTarget);
        const values: Values = { downloads_dir: String(form.get("downloads_dir") ?? "").trim() };
        for (const { name } of limits) values[name] = Number(form.get(name));
        save.reset();
        if (values.downloads_dir !== data.paths.downloads_dir) setPending(values);
        else save.mutate(values);
      }}>
        <fieldset disabled={busy || save.isPending} className="space-y-4 disabled:opacity-60">
          <div>
            <label htmlFor="settings-downloads-dir" className="text-sm font-medium">Carpeta de descargas</label>
            <Input id="settings-downloads-dir" name="downloads_dir" className="mt-1 font-mono" required
              maxLength={4096} spellCheck={false} defaultValue={data.paths.downloads_dir} aria-describedby="downloads-dir-help" />
            <p id="downloads-dir-help" className="mt-1 text-xs text-muted-foreground">
              Cambiarla traslada también los archivos existentes. El destino debe estar vacío.
              En Docker usa una subcarpeta del volumen de datos{data.downloads_storage_root ? ` (${data.downloads_storage_root})` : ""};
              una ruta del host requiere un volumen montado previamente.
            </p>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            {limits.map(({ name, label, unit, max }) => (
              <div key={name}>
                <label htmlFor={`settings-${name}`} className="text-sm font-medium">{label}</label>
                <Input id={`settings-${name}`} name={name} className="mt-1" type="number" required min={1}
                  max={max} step={1} defaultValue={data.limits[name]} aria-describedby={`help-${name}`} />
                <p id={`help-${name}`} className="mt-1 text-xs text-muted-foreground">De 1 a {max.toLocaleString("es")}, en {unit}.</p>
              </div>
            ))}
          </div>
          <Button type="submit">{save.isPending ? "Guardando…" : "Guardar ajustes"}</Button>
        </fieldset>
      </form>
      {error && <p role="alert" className="mt-3 text-sm text-destructive">{error.message}</p>}
      {operation && operation.status !== "idle" && (
        <div className="mt-4 rounded-lg border border-border bg-muted p-3 text-sm" role="status" aria-live="polite">
          <p className="font-medium">{operation.status === "completed" ? "Traslado completado" :
            operation.status === "failed" ? "El traslado necesita atención" :
              operation.status === "queued" ? "Traslado en cola" : "Trasladando y verificando archivos…"}</p>
          <p className="mt-1 break-all text-xs text-muted-foreground">{operation.source} → {operation.destination}</p>
          {operation.error && <p className="mt-2 text-destructive">{operation.error}</p>}
          {busy && <>
            <p className="mt-2 text-xs text-muted-foreground">Las descargas quedan bloqueadas hasta terminar. Si el worker se interrumpió, puedes reintentar sin perder las copias verificadas.</p>
            <Button type="button" variant="outline" size="sm" className="mt-3" disabled={retry.isPending}
              onClick={() => retry.mutate()}>Reintentar traslado</Button>
          </>}
        </div>
      )}
      <ConfirmDialog open={pending !== null} onOpenChange={(open) => { if (!open && !save.isPending) setPending(null); }}
        title="Trasladar archivos existentes"
        description={`Se copiarán y verificarán las descargas de ${data.paths.downloads_dir} a ${pending?.downloads_dir ?? ""}. La carpeta anterior se vaciará solo después de verificar los archivos y guardar las nuevas rutas. No cierres ni desmontes los volúmenes durante el traslado.`}
        confirmLabel="Guardar y trasladar" busy={save.isPending}
        onConfirm={() => { if (pending) save.mutate({ ...pending, confirm_move: true }); }} />
    </Card>
  );
}
