"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Plus, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { toast } from "sonner";

import { JobTable } from "@/components/jobs";
import { ConfirmDialog, ErrorState, LoadingRows, MetricCard, PageHeader } from "@/components/states";
import { Button, Card, buttonVariants } from "@/components/ui";
import { apiFetch } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import type { ChatProfile } from "@/lib/types";

export default function ChatDetailPage() {
  const params = useParams<{ id: string }>();
  const chatId = decodeURIComponent(params.id);
  const queryClient = useQueryClient();
  const [cleanOpen, setCleanOpen] = useState(false);
  const profile = useQuery({
    queryKey: queryKeys.chat(chatId),
    queryFn: () => apiFetch<ChatProfile>(`/api/v1/chats/${encodeURIComponent(chatId)}`),
  });
  const clean = useMutation({
    mutationFn: () =>
      apiFetch<void>(`/api/v1/chats/${encodeURIComponent(chatId)}/downloads`, {
        method: "DELETE",
        body: JSON.stringify({ confirm: true }),
      }),
    onSuccess: () => {
      toast.success("Descargas del chat eliminadas");
      setCleanOpen(false);
      queryClient.invalidateQueries({ queryKey: queryKeys.chat(chatId) });
    },
    onError: (error) => toast.error(error.message),
  });

  if (profile.isError) {
    return (
      <>
        <PageHeader title="Chat" />
        <ErrorState description={profile.error.message} onRetry={() => profile.refetch()} />
      </>
    );
  }
  if (profile.isLoading || !profile.data) {
    return (
      <>
        <PageHeader title="Chat" />
        <LoadingRows rows={4} />
      </>
    );
  }
  const data = profile.data;
  return (
    <>
      <PageHeader
        title={data.chat_title}
        description={data.chat_id}
        actions={
          <>
            <Link href="/chats" className={cn(buttonVariants({ variant: "outline" }), "gap-2")}>
              <ArrowLeft className="h-4 w-4" />
              Chats
            </Link>
            <Link
              href={`/downloads/new?chat_id=${encodeURIComponent(data.chat_id)}&chat_title=${encodeURIComponent(data.chat_title)}`}
              className={cn(buttonVariants(), "gap-2")}
            >
              <Plus className="h-4 w-4" />
              Nueva descarga
            </Link>
          </>
        }
      />
      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard label="Jobs" value={data.jobs.length} hint="Historial del chat" />
        <MetricCard label="Archivos" value={data.downloaded_files} hint="Descargados" />
        <MetricCard label="Tamaño" value={data.downloaded_size} hint="Carpeta del chat" />
        <MetricCard
          label="Export"
          value={data.export_exists ? "Listo" : "Faltante"}
          hint={
            data.export_updated_at
              ? new Date(data.export_updated_at).toLocaleString("es-MX")
              : "Sin actualizar"
          }
        />
      </section>

      <Card className="mt-4 p-5">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 className="font-semibold">Descargas del chat</h2>
            <p className="text-xs text-muted-foreground">
              Limpia solo los archivos descargados; no borra exports ni jobs.
            </p>
          </div>
          <Button variant="danger" onClick={() => setCleanOpen(true)}>
            <Trash2 className="h-4 w-4" />
            Limpiar descargas
          </Button>
        </div>
      </Card>

      <Card className="mt-4 p-5">
        <h2 className="mb-3 font-semibold">Historial de jobs</h2>
        <JobTable jobs={data.jobs} />
      </Card>

      <ConfirmDialog
        open={cleanOpen}
        onOpenChange={setCleanOpen}
        title="Limpiar descargas del chat"
        description="Se borrarán los archivos descargados de este chat. Los jobs y exports se conservan. No se puede deshacer."
        confirmLabel="Limpiar descargas"
        danger
        busy={clean.isPending}
        onConfirm={() => clean.mutate()}
      />
    </>
  );
}
