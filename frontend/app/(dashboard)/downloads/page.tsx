"use client";

import { useQuery } from "@tanstack/react-query";
import { Plus, RefreshCw, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { JobTable } from "@/components/jobs";
import { EmptyState, ErrorState, LoadingRows, PageHeader, Pagination } from "@/components/states";
import { Button, Input, Select, buttonVariants } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import type { Job, Page } from "@/lib/types";

export default function DownloadsPage() {
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const params = useMemo(
    () => ({
      q: q.trim(),
      status,
      page,
      per_page: 20,
    }),
    [q, status, page],
  );
  const jobs = useQuery({
    queryKey: queryKeys.jobs(params),
    queryFn: () => {
      const search = new URLSearchParams();
      search.set("page", String(page));
      search.set("per_page", "20");
      if (q.trim()) search.set("q", q.trim());
      if (status) search.set("status", status);
      return apiFetch<Page<Job>>(`/api/v1/jobs?${search.toString()}`);
    },
    refetchInterval: 5_000,
  });

  return (
    <>
      <PageHeader
        title="Descargas"
        description="Historial de jobs, progreso y acciones."
        actions={
          <Link href="/downloads/new" className={cn(buttonVariants(), "gap-2")}>
            <Plus className="h-4 w-4" />
            Nueva descarga
          </Link>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <label className="relative min-w-56 flex-1">
          <span className="sr-only">Buscar jobs</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={q}
            onChange={(event) => {
              setQ(event.target.value);
              setPage(1);
            }}
            placeholder="Chat, hashtag, carpeta o error"
            className="pl-9"
          />
        </label>
        <label>
          <span className="sr-only">Estado</span>
          <Select
            value={status}
            onChange={(event) => {
              setStatus(event.target.value);
              setPage(1);
            }}
            className="w-44"
          >
            <option value="">Todos los estados</option>
            <option value="pending">Pendientes</option>
            <option value="running">En curso</option>
            <option value="completed">Completados</option>
            <option value="failed">Fallidos</option>
            <option value="cancelled">Cancelados</option>
          </Select>
        </label>
        <Button variant="outline" onClick={() => jobs.refetch()} aria-label="Actualizar">
          <RefreshCw className={cn("h-4 w-4", jobs.isFetching && "animate-spin")} />
          Actualizar
        </Button>
      </div>

      {jobs.isError ? (
        <ErrorState
          description={(jobs.error as Error).message}
          onRetry={() => jobs.refetch()}
        />
      ) : jobs.isLoading ? (
        <LoadingRows rows={6} />
      ) : jobs.data?.items.length ? (
        <>
          <JobTable jobs={jobs.data.items} />
          <Pagination
            page={jobs.data.page}
            pageCount={jobs.data.page_count}
            total={jobs.data.total}
            onPage={setPage}
          />
        </>
      ) : (
        <EmptyState
          title="No hay descargas"
          description="Ajusta los filtros o crea una descarga nueva."
          action={
            <Link href="/downloads/new" className={buttonVariants()}>
              Nueva descarga
            </Link>
          }
        />
      )}
    </>
  );
}
