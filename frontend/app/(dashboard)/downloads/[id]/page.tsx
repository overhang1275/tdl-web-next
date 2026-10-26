"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Ban, RotateCcw, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { EventTimeline, FileGrid, LogViewer } from "@/components/files";
import { JobProgress } from "@/components/jobs";
import {
  ConfirmDialog,
  ErrorState,
  LoadingRows,
  PageHeader,
  Pagination,
} from "@/components/states";
import { Button, Card, buttonVariants } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import type { EventItem, Job, JobFile, LogResult, Page } from "@/lib/types";

export default function JobDetailPage() {
  const params = useParams<{ id: string }>();
  const jobId = Number(params.id);
  const queryClient = useQueryClient();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [filesPage, setFilesPage] = useState(1);

  const job = useQuery({
    queryKey: queryKeys.job(jobId),
    queryFn: () => apiFetch<Job>(`/api/v1/jobs/${jobId}`),
    refetchInterval: (query) => {
      const data = query.state.data;
      return data && (data.status === "pending" || data.status === "running") ? 2_000 : false;
    },
  });
  const files = useQuery({
    queryKey: queryKeys.jobFiles(jobId, { page: filesPage, per_page: 24 }),
    queryFn: () => apiFetch<Page<JobFile>>(`/api/v1/jobs/${jobId}/files?page=${filesPage}&per_page=24`),
    refetchInterval: job.data?.status === "pending" || job.data?.status === "running" ? 5_000 : false,
  });
  useEffect(() => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.jobFiles(jobId) });
  }, [job.data?.status, jobId, queryClient]);
  const logs = useQuery({
    queryKey: queryKeys.jobLogs(jobId),
    queryFn: () => apiFetch<LogResult>(`/api/v1/jobs/${jobId}/logs`),
    refetchInterval: 5_000,
  });
  const events = useQuery({
    queryKey: queryKeys.jobEvents(jobId),
    queryFn: () => apiFetch<EventItem[]>(`/api/v1/jobs/${jobId}/events`),
    refetchInterval: 5_000,
  });

  function refresh() {
    queryClient.invalidateQueries({ queryKey: queryKeys.job(jobId) });
    queryClient.invalidateQueries({ queryKey: queryKeys.jobFiles(jobId) });
  }

  const cancel = useMutation({
    mutationFn: () => apiFetch<Job>(`/api/v1/jobs/${jobId}/cancel`, { method: "POST" }),
    onSuccess: () => {
      toast.success("Cancelación solicitada");
      refresh();
    },
    onError: (error) => toast.error(error.message),
  });
  const retry = useMutation({
    mutationFn: (mode: "pending" | "failed") =>
      apiFetch<Job>(`/api/v1/jobs/${jobId}/retry?mode=${mode}`, { method: "POST" }),
    onSuccess: () => {
      toast.success("Reintento encolado");
      refresh();
    },
    onError: (error) => toast.error(error.message),
  });
  const remove = useMutation({
    mutationFn: () =>
      apiFetch<Job>(`/api/v1/jobs/${jobId}`, {
        method: "DELETE",
        body: JSON.stringify({ confirm: true }),
      }),
    onSuccess: () => {
      toast.success("Eliminación en curso");
      setDeleteOpen(false);
      refresh();
    },
    onError: (error) => toast.error(error.message),
  });

  if (job.isError) {
    return (
      <>
        <PageHeader title={`Job #${jobId}`} />
        <ErrorState description={job.error.message} onRetry={() => job.refetch()} />
      </>
    );
  }
  if (job.isLoading || !job.data) {
    return (
      <>
        <PageHeader title={`Job #${jobId}`} />
        <LoadingRows rows={4} />
      </>
    );
  }
  const data = job.data;
  const active = data.status === "pending" || data.status === "running";
  return (
    <>
      <PageHeader
        title={`Job #${data.id}`}
        description={`${data.chat_title ?? data.chat_id} · ${data.output_subfolder}`}
        actions={
          <>
            <Link
              href="/downloads"
              className={cn(buttonVariants({ variant: "outline" }), "gap-2")}
            >
              <ArrowLeft className="h-4 w-4" />
              Descargas
            </Link>
            {active ? (
              <Button
                variant="outline"
                onClick={() => cancel.mutate()}
                disabled={cancel.isPending}
              >
                <Ban className="h-4 w-4" />
                Cancelar
              </Button>
            ) : null}
            {data.status === "failed" || data.status === "cancelled" ? (
              <Button onClick={() => retry.mutate("pending")} disabled={retry.isPending}>
                <RotateCcw className="h-4 w-4" />
                Reintentar pendientes
              </Button>
            ) : null}
            {data.status === "failed" && data.total_failed_files > 0 ? (
              <Button
                variant="outline"
                onClick={() => retry.mutate("failed")}
                disabled={retry.isPending}
              >
                Reintentar fallidos
              </Button>
            ) : null}
            <Button variant="danger" onClick={() => setDeleteOpen(true)}>
              <Trash2 className="h-4 w-4" />
              Eliminar
            </Button>
          </>
        }
      />

      <JobProgress job={data} />

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card className="p-5">
          <h2 className="font-semibold">Eventos</h2>
          <div className="mt-3">
            {events.isLoading ? <LoadingRows rows={3} /> : <EventTimeline events={events.data ?? []} />}
          </div>
        </Card>
        <Card className="p-5">
          <h2 className="font-semibold">Logs</h2>
          <div className="mt-3">
            {logs.isLoading ? (
              <LoadingRows rows={3} />
            ) : (
              <LogViewer content={logs.data?.content ?? ""} truncated={logs.data?.truncated ?? false} />
            )}
          </div>
        </Card>
      </div>

      <Card className="mt-4 p-5">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="font-semibold">Archivos</h2>
          <span className="text-xs text-muted-foreground">
            {files.data?.total ?? 0} archivos
          </span>
        </div>
        {files.isError ? (
          <ErrorState description={files.error.message} onRetry={() => files.refetch()} />
        ) : files.isLoading ? (
          <LoadingRows rows={2} />
        ) : (
          <FileGrid files={files.data?.items ?? []} />
        )}
        {files.data ? <Pagination page={files.data.page} pageCount={files.data.page_count} total={files.data.total} onPage={setFilesPage} /> : null}
      </Card>

      <ConfirmDialog
        open={deleteOpen}
        onOpenChange={setDeleteOpen}
        title={`Eliminar job #${data.id}`}
        description="Se cancelará si está activo y se borrará la carpeta física con wipe. Esta acción no se puede deshacer."
        confirmLabel="Eliminar job"
        danger
        busy={remove.isPending}
        onConfirm={() => remove.mutate()}
      />
    </>
  );
}
