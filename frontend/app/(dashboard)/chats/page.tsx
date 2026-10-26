"use client";

import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Search } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { EmptyState, ErrorState, LoadingRows, PageHeader, Pagination } from "@/components/states";
import { Badge, Button, Input, Select } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import type { ChatPage } from "@/lib/types";

export default function ChatsPage() {
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [page, setPage] = useState(1);
  const [refresh, setRefresh] = useState(false);
  const params = useMemo(() => ({ q, type, page, refresh }), [q, type, page, refresh]);
  const chats = useQuery({
    queryKey: queryKeys.chats(params),
    queryFn: () => {
      const search = new URLSearchParams({
        q,
        chat_type: type,
        page: String(page),
        per_page: "25",
        refresh: String(refresh),
      });
      return apiFetch<ChatPage>(`/api/v1/chats?${search.toString()}`);
    },
  });

  const typeCounts = chats.data?.type_counts ?? {};
  return (
    <>
      <PageHeader
        title="Chats"
        description="Canales, grupos y conversaciones disponibles en la sesión de tdl."
        actions={
          <Button
            variant="outline"
            onClick={() => {
              setRefresh(true);
              chats.refetch();
            }}
          >
            <RefreshCw className={cn("h-4 w-4", chats.isFetching && "animate-spin")} />
            Actualizar caché
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <label className="relative min-w-56 flex-1">
          <span className="sr-only">Buscar chats</span>
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={q}
            onChange={(event) => {
              setQ(event.target.value);
              setPage(1);
            }}
            placeholder="Nombre, @usuario o ID"
            className="pl-9"
          />
        </label>
        <Select
          value={type}
          onChange={(event) => {
            setType(event.target.value);
            setPage(1);
          }}
          className="w-44"
        >
          <option value="">Todos ({chats.data?.total ?? 0})</option>
          <option value="channel">Canales ({typeCounts.channel ?? 0})</option>
          <option value="group">Grupos ({typeCounts.group ?? 0})</option>
          <option value="private">Privados ({typeCounts.private ?? 0})</option>
        </Select>
      </div>

      {chats.data?.cached_at ? (
        <p className="mb-3 text-xs text-muted-foreground">
          Caché: {new Date(chats.data.cached_at).toLocaleString("es-MX")}
          {chats.data.refreshed ? " · recién actualizado" : ""}
        </p>
      ) : null}

      {chats.isError ? (
        <ErrorState description={chats.error.message} onRetry={() => chats.refetch()} />
      ) : chats.isLoading ? (
        <LoadingRows rows={6} />
      ) : chats.data?.items.length ? (
        <>
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="py-2 pr-3 font-medium">Chat</th>
                  <th className="py-2 pr-3 font-medium">Tipo</th>
                  <th className="py-2 pr-3 font-medium">Topics</th>
                  <th className="py-2 text-right font-medium">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {chats.data.items.map((chat) => (
                  <tr key={chat.id} className="border-b border-border/70 last:border-0">
                    <td className="py-3 pr-3">
                      <p className="font-medium">{chat.title}</p>
                      <p className="mono text-[11px] text-muted-foreground">
                        {chat.id}
                        {chat.username ? ` · @${chat.username}` : ""}
                      </p>
                    </td>
                    <td className="py-3 pr-3">
                      <Badge variant="outline">{chat.type || "chat"}</Badge>
                    </td>
                    <td className="py-3 pr-3 tabular-nums text-muted-foreground">
                      {chat.topics_count}
                    </td>
                    <td className="py-3 text-right">
                      <Link
                        href={`/chats/${encodeURIComponent(chat.id)}`}
                        className="text-xs font-medium text-primary hover:underline"
                      >
                        Perfil
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="grid gap-2 md:hidden">
            {chats.data.items.map((chat) => (
              <Link
                key={chat.id}
                href={`/chats/${encodeURIComponent(chat.id)}`}
                className="rounded-xl border border-border bg-card p-4"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{chat.title}</p>
                    <p className="mono text-[11px] text-muted-foreground">{chat.id}</p>
                  </div>
                  <Badge variant="outline">{chat.type || "chat"}</Badge>
                </div>
              </Link>
            ))}
          </div>
          <Pagination
            page={chats.data.page}
            pageCount={chats.data.page_count}
            total={chats.data.total}
            onPage={setPage}
          />
        </>
      ) : (
        <EmptyState
          title="Sin chats en caché"
          description="Actualiza el caché para leerlos desde tdl."
          action={
            <Button
              onClick={() => {
                setRefresh(true);
                chats.refetch();
              }}
            >
              Actualizar caché
            </Button>
          }
        />
      )}
    </>
  );
}
