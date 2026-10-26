"use client";

import { ArrowUpRight, Clock3, Download, Gauge } from "lucide-react";
import Link from "next/link";

import { Badge, Card, Progress } from "@/components/ui";
import { StatusBadge } from "@/components/states";
import { formatBytes, formatDate, formatDuration, statusLabel } from "@/lib/format";
import type { Job } from "@/lib/types";

export function JobProgress({ job }: { job: Job }) {
  const active = job.status === "pending" || job.status === "running";
  const pending = Math.max(
    job.total_filtered_messages - job.total_downloaded_files - job.total_failed_files,
    0,
  );
  const showSpeed = active && job.speed_bps > 0;
  const showEta = active && job.eta_seconds !== null;
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
            Progreso
          </p>
          <div className="mt-2 flex items-center gap-2">
            <StatusBadge status={job.status} />
            <Badge variant="outline">{statusLabel(job.stage)}</Badge>
            {job.deletion_requested ? <Badge variant="danger">Eliminando</Badge> : null}
          </div>
        </div>
        <div className="text-right">
          <p className="text-2xl font-semibold tabular-nums">
            {job.progress_percent === null ? "—" : `${Math.round(job.progress_percent)}%`}
          </p>
          <p className="text-xs text-muted-foreground">
            {job.transfer_initialized ? "archivos verificados" : "preparando selección"}
          </p>
        </div>
      </div>
      <Progress value={job.progress_percent} className="mt-4" />
      <div className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
        <div>
          <p className="text-xs text-muted-foreground">Encontrados</p>
          <p className="font-medium tabular-nums">{job.total_filtered_messages}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Descargados</p>
          <p className="font-medium tabular-nums">{job.total_downloaded_files}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Pendientes</p>
          <p className="font-medium tabular-nums">{pending}</p>
        </div>
        <div>
          <p className="text-xs text-muted-foreground">Fallidos</p>
          <p className="font-medium tabular-nums">{job.total_failed_files}</p>
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-4 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5">
          <Download className="h-3.5 w-3.5" />
          {formatBytes(job.downloaded_bytes)}
          {job.total_expected_bytes !== null
            ? ` de ${formatBytes(job.total_expected_bytes)}`
            : ""}
        </span>
        {showSpeed ? (
          <span className="inline-flex items-center gap-1.5">
            <Gauge className="h-3.5 w-3.5" />
            {formatBytes(job.speed_bps)}/s
          </span>
        ) : null}
        {showEta ? (
          <span className="inline-flex items-center gap-1.5">
            <Clock3 className="h-3.5 w-3.5" />
            ETA {formatDuration(job.eta_seconds)}
          </span>
        ) : null}
      </div>
      {job.deletion_error ? (
        <p className="mt-3 rounded-lg bg-destructive/10 px-3 py-2 text-xs text-destructive">
          {job.deletion_error}
        </p>
      ) : null}
    </Card>
  );
}

export function JobTable({ jobs }: { jobs: Job[] }) {
  if (!jobs.length) {
    return (
      <p className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
        No hay descargas todavía.
      </p>
    );
  }
  return (
    <>
      <div className="hidden overflow-x-auto md:block">
        <table className="w-full text-left text-sm">
          <thead className="border-b border-border text-xs uppercase tracking-wide text-muted-foreground">
            <tr>
              <th className="py-2 pr-3 font-medium">Job</th>
              <th className="py-2 pr-3 font-medium">Chat</th>
              <th className="py-2 pr-3 font-medium">Estado</th>
              <th className="py-2 pr-3 font-medium">Progreso</th>
              <th className="py-2 pr-3 font-medium">Archivos</th>
              <th className="py-2 pr-3 font-medium">Creado</th>
              <th className="py-2 font-medium sr-only">Abrir</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.id} className="border-b border-border/70 last:border-0">
                <td className="py-3 pr-3 mono text-xs text-muted-foreground">#{job.id}</td>
                <td className="max-w-56 truncate py-3 pr-3 font-medium">
                  {job.chat_title ?? job.chat_id}
                </td>
                <td className="py-3 pr-3">
                  <StatusBadge status={job.status} />
                </td>
                <td className="py-3 pr-3">
                  <div className="flex items-center gap-2">
                    <Progress value={job.progress_percent} className="w-24" />
                    <span className="w-10 text-right text-xs tabular-nums text-muted-foreground">
                      {job.progress_percent === null ? "—" : `${Math.round(job.progress_percent)}%`}
                    </span>
                  </div>
                </td>
                <td className="py-3 pr-3 text-xs tabular-nums text-muted-foreground">
                  {job.total_downloaded_files}/{job.total_filtered_messages}
                </td>
                <td className="py-3 pr-3 text-xs text-muted-foreground">
                  {formatDate(job.created_at)}
                </td>
                <td className="py-3 text-right">
                  <Link
                    href={`/downloads/${job.id}`}
                    className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
                  >
                    Abrir <ArrowUpRight className="h-3.5 w-3.5" />
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="grid gap-2 md:hidden">
        {jobs.map((job) => (
          <JobCard key={job.id} job={job} />
        ))}
      </div>
    </>
  );
}

export function JobCard({ job }: { job: Job }) {
  return (
    <Link
      href={`/downloads/${job.id}`}
      className="block rounded-xl border border-border bg-card p-4 transition-colors hover:bg-muted/50"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="mono text-[11px] text-muted-foreground">#{job.id}</p>
          <p className="truncate font-medium">{job.chat_title ?? job.chat_id}</p>
        </div>
        <StatusBadge status={job.status} />
      </div>
      <div className="mt-3 flex items-center gap-2">
        <Progress value={job.progress_percent} className="flex-1" />
        <span className="text-xs tabular-nums text-muted-foreground">
          {job.progress_percent === null ? "—" : `${Math.round(job.progress_percent)}%`}
        </span>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        {job.total_downloaded_files}/{job.total_filtered_messages} archivos ·{" "}
        {formatBytes(job.downloaded_bytes)}
        {job.total_failed_files ? ` · ${job.total_failed_files} fallidos` : ""}
      </p>
    </Link>
  );
}
