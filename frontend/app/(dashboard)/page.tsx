"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, AlertTriangle, FileDown, HardDrive, Plus } from "lucide-react";
import Link from "next/link";

import { JobTable } from "@/components/jobs";
import {
  EmptyState,
  ErrorState,
  LoadingRows,
  MetricCard,
  PageHeader,
  StatusBadge,
} from "@/components/states";
import { buttonVariants } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { formatDate, formatRelative } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import type { Dashboard, Job, Page, Status } from "@/lib/types";

export default function DashboardPage() {
  const dashboard = useQuery({
    queryKey: queryKeys.dashboard,
    queryFn: () => apiFetch<Dashboard>("/api/v1/dashboard"),
  });
  const status = useQuery({
    queryKey: queryKeys.status,
    queryFn: () => apiFetch<Status>("/api/v1/status"),
    refetchInterval: 30_000,
  });
  const active = useQuery({
    queryKey: queryKeys.jobs({ status: "active", per_page: 6 }),
    queryFn: () =>
      apiFetch<Page<Job>>("/api/v1/jobs?status=pending&status=running&per_page=6"),
    refetchInterval: 5_000,
  });

  if (dashboard.isError) {
    return (
      <>
        <PageHeader title="Resumen" description="Estado general de la consola." />
        <ErrorState
          description={(dashboard.error as Error).message}
          onRetry={() => dashboard.refetch()}
        />
      </>
    );
  }

  const metrics = dashboard.data;
  return (
    <>
      <PageHeader
        title="Resumen"
        description="Estado de la sesión, la cola y las descargas recientes."
        actions={
          <Link href="/downloads/new" className={cn(buttonVariants(), "gap-2")}>
            <Plus className="h-4 w-4" />
            Nueva descarga
          </Link>
        }
      />

      <section className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <MetricCard
          label="Jobs activos"
          value={metrics?.active_jobs ?? "—"}
          hint="Pendientes o en curso"
          icon={<Activity className="h-4 w-4" />}
        />
        <MetricCard
          label="Fallidos"
          value={metrics?.failed_jobs ?? "—"}
          hint="Requieren revisión"
          icon={<AlertTriangle className="h-4 w-4" />}
        />
        <MetricCard
          label="Archivos"
          value={metrics?.downloaded_files ?? "—"}
          hint="Registrados en jobs"
          icon={<FileDown className="h-4 w-4" />}
        />
        <MetricCard
          label="Disco usado"
          value={metrics?.disk_usage ?? "—"}
          hint="Carpeta de descargas"
          icon={<HardDrive className="h-4 w-4" />}
        />
      </section>

      <section className="mt-4 grid gap-4 xl:grid-cols-[1.5fr_1fr]">
        <div className="rounded-xl border border-border bg-card p-5">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h2 className="font-semibold">En curso</h2>
              <p className="text-xs text-muted-foreground">Se actualiza cada 5 segundos.</p>
            </div>
            <Link href="/downloads" className="text-xs font-medium text-primary hover:underline">
              Ver historial
            </Link>
          </div>
          {active.isError ? (
            <ErrorState description={active.error.message} onRetry={() => active.refetch()} />
          ) : active.isLoading ? (
            <LoadingRows rows={3} />
          ) : active.data?.items.length ? (
            <JobTable jobs={active.data.items} />
          ) : (
            <EmptyState
              title="Nada en cola"
              description="Crea una descarga para ver el progreso aquí."
            />
          )}
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border border-border bg-card p-5">
            <h2 className="font-semibold">Servicios</h2>
            <dl className="mt-3 space-y-2 text-sm">
              <div className="flex items-center justify-between gap-2">
                <dt className="text-muted-foreground">Sesión de Telegram</dt>
                <dd>
                  <StatusBadge status={status.data?.session_active ? "completed" : "pending"} />
                </dd>
              </div>
              <div className="flex items-center justify-between gap-2">
                <dt className="text-muted-foreground">Redis</dt>
                <dd>
                  <StatusBadge status={status.data?.redis_connected ? "completed" : "failed"} />
                </dd>
              </div>
              <div className="flex items-center justify-between gap-2">
                <dt className="text-muted-foreground">Worker</dt>
                <dd>
                  <StatusBadge status={status.data?.worker_connected ? "completed" : "failed"} />
                </dd>
              </div>
              <div className="flex items-center justify-between gap-2">
                <dt className="text-muted-foreground">Authentik</dt>
                <dd>
                  <StatusBadge
                    status={status.data?.authentik_configured ? "completed" : "pending"}
                  />
                </dd>
              </div>
            </dl>
            <p className="mt-3 text-xs text-muted-foreground">
              Versión {status.data?.version ?? "—"} · {metrics?.chat_counts.total ?? 0} chats
              {metrics?.chat_counts.cached_at
                ? ` · caché ${formatRelative(metrics.chat_counts.cached_at)}`
                : ""}
            </p>
          </div>

          <div className="rounded-xl border border-border bg-card p-5">
            <h2 className="font-semibold">Últimos errores</h2>
            {metrics?.latest_errors.length ? (
              <ul className="mt-3 space-y-2">
                {metrics.latest_errors.map((job) => (
                  <li key={job.id}>
                    <Link
                      href={`/downloads/${job.id}`}
                      className="block rounded-lg border border-border/70 p-3 text-sm hover:bg-muted/50"
                    >
                      <span className="mono text-[11px] text-muted-foreground">#{job.id}</span>
                      <p className="font-medium">{job.chat_title ?? job.chat_id}</p>
                      <p className="line-clamp-2 text-xs text-muted-foreground">
                        {job.error_message ?? "Job fallido"}
                      </p>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        {formatDate(job.finished_at ?? job.created_at)}
                      </p>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-3 text-sm text-muted-foreground">Sin errores recientes.</p>
            )}
          </div>
        </div>
      </section>
    </>
  );
}
