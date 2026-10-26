"use client";

import { useQuery } from "@tanstack/react-query";
import { Search as SearchIcon } from "lucide-react";
import Link from "next/link";
import { Suspense, useState } from "react";
import { useSearchParams } from "next/navigation";

import { EmptyState, ErrorState, LoadingRows, PageHeader } from "@/components/states";
import { Button, Card, Input } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import type { SearchResult } from "@/lib/types";

function SearchInner() {
  const params = useSearchParams();
  const [query, setQuery] = useState(params.get("q") ?? "");
  const [submitted, setSubmitted] = useState(params.get("q") ?? "");
  const result = useQuery({
    queryKey: queryKeys.search(submitted),
    queryFn: () => apiFetch<SearchResult>(`/api/v1/search?q=${encodeURIComponent(submitted)}`),
    enabled: submitted.trim().length > 0,
  });

  function submit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitted(query.trim());
  }

  const groups = [
    { key: "chats" as const, title: "Chats" },
    { key: "jobs" as const, title: "Jobs" },
    { key: "files" as const, title: "Archivos" },
  ];
  return (
    <>
      <PageHeader title="Buscar" description="Chats, jobs y archivos en un solo lugar." />
      <Card className="p-5">
        <form onSubmit={submit} className="flex flex-col gap-2 sm:flex-row">
          <label className="relative flex-1">
            <span className="sr-only">Buscar</span>
            <SearchIcon className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Nombre, ID, archivo, error…"
              className="pl-9"
              autoFocus
            />
          </label>
          <Button type="submit">Buscar</Button>
        </form>
      </Card>

      {!submitted ? (
        <div className="mt-4">
          <EmptyState title="Escribe algo para buscar" />
        </div>
      ) : result.isError ? (
        <div className="mt-4">
          <ErrorState description={result.error.message} onRetry={() => result.refetch()} />
        </div>
      ) : result.isLoading ? (
        <div className="mt-4">
          <LoadingRows rows={4} />
        </div>
      ) : (
        <div className="mt-4 grid gap-4 lg:grid-cols-3">
          {groups.map((group) => (
            <Card key={group.key} className="p-5">
              <h2 className="font-semibold">{group.title}</h2>
              <p className="text-xs text-muted-foreground">
                {result.data?.[group.key].length ?? 0} coincidencias
              </p>
              <div className="mt-3 space-y-2">
                {(result.data?.[group.key] ?? []).map((item) => (
                  <div key={`${group.key}-${item.id}`} className="rounded-lg border border-border/70 p-3">
                    <Link href={item.url} className="text-sm font-medium hover:underline">
                      {item.title}
                    </Link>
                    <p className="text-xs text-muted-foreground">{item.subtitle}</p>
                    {item.download_url ? (
                      <a
                        href={item.download_url}
                        className="mt-1 inline-block text-xs text-primary hover:underline"
                      >
                        Descargar
                      </a>
                    ) : null}
                  </div>
                ))}
                {!result.data?.[group.key].length ? (
                  <p className="text-xs text-muted-foreground">Sin resultados.</p>
                ) : null}
              </div>
            </Card>
          ))}
        </div>
      )}
    </>
  );
}

export default function SearchPage() {
  return (
    <Suspense fallback={<LoadingRows rows={3} />}>
      <SearchInner />
    </Suspense>
  );
}
