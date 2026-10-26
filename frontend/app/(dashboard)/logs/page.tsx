"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";

import { EmptyState, ErrorState, LoadingRows, PageHeader, Pagination, StatusBadge } from "@/components/states";
import { Card } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { formatDate } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Job, Page } from "@/lib/types";

export default function LogsPage() {
  const [page, setPage] = useState(1);
  const jobs = useQuery({
    queryKey: queryKeys.jobs({ page, per_page: 20, logs: 1 }),
    queryFn: () => apiFetch<Page<Job>>(`/api/v1/jobs?page=${page}&per_page=20`),
  });
  return (
    <>
      <PageHeader
        title="Registros"
        description="Actividad reciente de jobs y acceso a sus logs."
      />
      {jobs.isError ? (
        <ErrorState description={jobs.error.message} onRetry={() => jobs.refetch()} />
      ) : jobs.isLoading ? (
        <LoadingRows rows={6} />
      ) : jobs.data?.items.length ? (
        <Card className="p-5">
          <ul className="divide-y divide-border">
            {jobs.data.items.map((job) => (
              <li key={job.id} className="flex flex-wrap items-center justify-between gap-2 py-3">
                <div className="min-w-0">
                  <Link
                    href={`/downloads/${job.id}`}
                    className="font-medium hover:underline"
                  >
                    #{job.id} · {job.chat_title ?? job.chat_id}
                  </Link>
                  <p className="text-xs text-muted-foreground">
                    {formatDate(job.finished_at ?? job.created_at)} ·{" "}
                    {job.total_downloaded_files} archivos
                    {job.error_message ? ` · ${job.error_message.slice(0, 90)}` : ""}
                  </p>
                </div>
                <StatusBadge status={job.status} />
              </li>
            ))}
          </ul>
          <Pagination
            page={jobs.data.page}
            pageCount={jobs.data.page_count}
            total={jobs.data.total}
            onPage={setPage}
          />
        </Card>
      ) : (
        <EmptyState title="Sin actividad" description="Los jobs aparecerán aquí." />
      )}
    </>
  );
}
