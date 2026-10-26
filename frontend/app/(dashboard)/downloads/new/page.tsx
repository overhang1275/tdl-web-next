"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Search } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import { useForm, useWatch } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { ConfirmDialog, PageHeader } from "@/components/states";
import { Button, Card, Input, Select, buttonVariants } from "@/components/ui";
import { apiFetch, ApiError } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import type { Chat, ChatPage, Job, Template } from "@/lib/types";

const schema = z
  .object({
    chat_id: z.string().min(1, "Elige un chat o escribe su ID."),
    chat_title: z.string().optional(),
    hashtag: z.string().optional(),
    media_type: z.enum(["all", "video", "image", "audio", "document"]),
    search_text: z.string().optional(),
    date_from: z.string().optional(),
    date_to: z.string().optional(),
    output_subfolder: z
      .string()
      .min(1, "La subcarpeta es obligatoria.")
      .regex(/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/, "Solo letras, números, punto, guion y guion bajo."),
    skip_same: z.boolean(),
    refresh_export: z.boolean(),
    export_only: z.boolean(),
  })
  .refine(
    (values) =>
      !values.date_from || !values.date_to || values.date_from <= values.date_to,
    { message: "La fecha Desde debe ser menor o igual que Hasta.", path: ["date_to"] },
  );

type FormValues = z.infer<typeof schema>;

const defaults: FormValues = {
  chat_id: "",
  chat_title: "",
  hashtag: "",
  media_type: "all",
  search_text: "",
  date_from: "",
  date_to: "",
  output_subfolder: "download",
  skip_same: true,
  refresh_export: true,
  export_only: false,
};

export default function NewDownloadPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [chatQuery, setChatQuery] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [templateName, setTemplateName] = useState("");
  const [deleteTemplateOpen, setDeleteTemplateOpen] = useState(false);
  const chats = useQuery({
    queryKey: queryKeys.chats({ per_page: 100 }),
    queryFn: () => apiFetch<ChatPage>("/api/v1/chats?per_page=100"),
  });
  const templates = useQuery({
    queryKey: queryKeys.templates,
    queryFn: () => apiFetch<Template[]>("/api/v1/templates"),
  });
  const {
    register,
    handleSubmit,
    setValue,
    getValues,
    control,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema), defaultValues: defaults });
  const chatId = useWatch({ control, name: "chat_id" });
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const id = params.get("chat_id");
    if (!id) return;
    setValue("chat_id", id, { shouldValidate: true });
    setValue("chat_title", params.get("chat_title") ?? "");
    if (params.get("refresh_export") === "true") setValue("refresh_export", true);
    if (params.get("export_only") === "true") setValue("export_only", true);
  }, [setValue]);
  const filteredChats = useMemo(() => {
    const items = chats.data?.items ?? [];
    const query = chatQuery.trim().toLowerCase();
    if (!query) return items.slice(0, 12);
    return items
      .filter((chat) =>
        `${chat.title} ${chat.id} ${chat.username}`.toLowerCase().includes(query),
      )
      .slice(0, 12);
  }, [chats.data, chatQuery]);

  function selectChat(chat: Chat) {
    setValue("chat_id", chat.id, { shouldValidate: true });
    setValue("chat_title", chat.title);
    setChatQuery("");
  }

  function applyTemplate(templateId: string) {
    setTemplateId(templateId);
    const template = templates.data?.find((item) => String(item.id) === templateId);
    setTemplateName(template?.name ?? "");
    if (!template) return;
    setValue("chat_id", template.chat_id ?? "");
    setValue("chat_title", template.chat_title ?? "");
    setValue("hashtag", template.hashtag ?? "");
    setValue("media_type", template.media_type as FormValues["media_type"]);
    setValue("search_text", template.search_text ?? "");
    setValue("date_from", template.date_from ?? "");
    setValue("date_to", template.date_to ?? "");
    setValue("output_subfolder", template.output_subfolder ?? "download");
    setValue("skip_same", template.skip_same);
    setValue("refresh_export", template.refresh_export);
    setValue("export_only", template.export_only);
  }

  const saveTemplate = useMutation({
    mutationFn: async (method: "POST" | "PUT") => {
      if (!templateName.trim()) throw new Error("Escribe un nombre para la plantilla.");
      const values = getValues();
      return apiFetch<Template>(`/api/v1/templates${method === "PUT" ? `/${templateId}` : ""}`, {
        method,
        body: JSON.stringify({ ...values, name: templateName.trim(), chat_id: values.chat_id.trim() || null,
          date_from: values.date_from || null, date_to: values.date_to || null }),
      });
    },
    onSuccess: async (template) => {
      await queryClient.invalidateQueries({ queryKey: queryKeys.templates });
      setTemplateId(String(template.id));
      setTemplateName(template.name);
      toast.success("Plantilla guardada");
    },
    onError: (error) => toast.error(error.message),
  });
  const deleteTemplate = useMutation({
    mutationFn: () => apiFetch<void>(`/api/v1/templates/${templateId}`, { method: "DELETE", body: JSON.stringify({ confirm: true }) }),
    onSuccess: async () => {
      setTemplateId("");
      setTemplateName("");
      setDeleteTemplateOpen(false);
      await queryClient.invalidateQueries({ queryKey: queryKeys.templates });
      toast.success("Plantilla eliminada");
    },
    onError: (error) => toast.error(error.message),
  });

  async function onSubmit(values: FormValues) {
    const payload = {
      chat_id: values.chat_id.trim(),
      chat_title: values.chat_title?.trim() || null,
      hashtag: values.hashtag?.trim() || null,
      media_type: values.media_type,
      search_text: values.search_text?.trim() || null,
      date_from: values.date_from || null,
      date_to: values.date_to || null,
      skip_same: values.skip_same,
      refresh_export: values.refresh_export,
      export_only: values.export_only,
      output_subfolder: values.output_subfolder.trim(),
    };
    try {
      const job = await apiFetch<Job>("/api/v1/jobs", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.getRandomValues(new Uint32Array(4)).join("-") },
        body: JSON.stringify(payload),
      });
      toast.success(`Job #${job.id} creado`);
      router.push(`/downloads/${job.id}`);
    } catch (error) {
      if (error instanceof ApiError && error.code === "duplicate_job") {
        const jobId = (error.detail as { job_id?: number } | undefined)?.job_id;
        toast.error(`Ya hay un job activo${jobId ? ` (#${jobId})` : ""} con esa configuración.`);
        return;
      }
      toast.error(error instanceof Error ? error.message : "No se pudo crear el job.");
    }
  }

  return (
    <>
      <PageHeader
        title="Nueva descarga"
        description="Elige el chat, filtra el contenido y crea el job."
        actions={
          <Link href="/downloads" className={cn(buttonVariants({ variant: "outline" }), "gap-2")}>
            <ArrowLeft className="h-4 w-4" />
            Volver
          </Link>
        }
      />

      <form onSubmit={handleSubmit(onSubmit)} className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
        <div className="space-y-4">
          <Card className="p-5">
            <h2 className="font-semibold">Origen</h2>
            <p className="text-xs text-muted-foreground">
              Chat o canal de Telegram. También puedes escribir el ID o @usuario.
            </p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <label className="sm:col-span-2">
                <span className="mb-1 block text-xs font-medium">Chat</span>
                <div className="relative">
                  <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    {...register("chat_id")}
                    id="chat-id"
                    autoComplete="off"
                    aria-invalid={Boolean(errors.chat_id)}
                    aria-describedby={errors.chat_id ? "chat-id-error" : undefined}
                    value={chatQuery || chatId}
                    onChange={(event) => {
                      setChatQuery(event.target.value);
                      setValue("chat_id", event.target.value, { shouldValidate: true });
                    }}
                    placeholder="Buscar o escribir -1001234567890 / @canal"
                    className="pl-9"
                  />
                </div>
                {errors.chat_id ? (
                  <span id="chat-id-error" role="alert" className="mt-1 block text-xs text-destructive">{errors.chat_id.message}</span>
                ) : null}
                {chatQuery ? (
                  <div className="mt-2 max-h-56 overflow-auto rounded-lg border border-border bg-card">
                    {filteredChats.length ? (
                      filteredChats.map((chat) => (
                        <button
                          type="button"
                          key={chat.id}
                          onClick={() => selectChat(chat)}
                          className="flex w-full items-center justify-between gap-2 border-b border-border/60 px-3 py-2 text-left text-sm last:border-0 hover:bg-muted"
                        >
                          <span className="truncate">{chat.title}</span>
                          <span className="mono text-[11px] text-muted-foreground">{chat.id}</span>
                        </button>
                      ))
                    ) : (
                      <p className="p-3 text-xs text-muted-foreground">
                        Sin coincidencias en el caché. Puedes usar el ID escrito.
                      </p>
                    )}
                  </div>
                ) : null}
              </label>
              <label>
                <span className="mb-1 block text-xs font-medium">Título (opcional)</span>
                <Input {...register("chat_title")} placeholder="Nombre visible" />
              </label>
              <label>
                <span className="mb-1 block text-xs font-medium">Tipo de archivo</span>
                <Select {...register("media_type")}>
                  <option value="all">Todos</option>
                  <option value="video">Video</option>
                  <option value="image">Imagen</option>
                  <option value="audio">Audio</option>
                  <option value="document">Documento</option>
                </Select>
              </label>
            </div>
          </Card>

          <Card className="p-5">
            <h2 className="font-semibold">Filtros</h2>
            <p className="text-xs text-muted-foreground">Se aplican al export del chat.</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <label>
                <span className="mb-1 block text-xs font-medium">Texto</span>
                <Input {...register("search_text")} placeholder="Búsqueda opcional" />
              </label>
              <label>
                <span className="mb-1 block text-xs font-medium">Hashtag</span>
                <Input {...register("hashtag")} placeholder="#tag" />
              </label>
              <label>
                <span className="mb-1 block text-xs font-medium">Desde</span>
                <Input type="date" {...register("date_from")} />
              </label>
              <label>
                <span className="mb-1 block text-xs font-medium">Hasta</span>
                <Input type="date" {...register("date_to")} />
                {errors.date_to ? (
                  <span className="mt-1 block text-xs text-destructive">
                    {errors.date_to.message}
                  </span>
                ) : null}
              </label>
            </div>
          </Card>
        </div>

        <div className="space-y-4">
          <Card className="p-5">
            <h2 className="font-semibold">Destino y opciones</h2>
            <div className="mt-4 space-y-3">
              <label>
                <span className="mb-1 block text-xs font-medium">Subcarpeta</span>
                <Input {...register("output_subfolder")} placeholder="download" />
                {errors.output_subfolder ? (
                  <span className="mt-1 block text-xs text-destructive">
                    {errors.output_subfolder.message}
                  </span>
                ) : null}
              </label>
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" {...register("skip_same")} className="mt-1" />
                <span>
                  Omitir archivos iguales
                  <span className="block text-xs text-muted-foreground">
                    Reutiliza archivos completos ya verificados.
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" {...register("refresh_export")} className="mt-1" />
                <span>
                  Actualizar export.json
                  <span className="block text-xs text-muted-foreground">
                    Si lo desactivas, se reutiliza el export existente.
                  </span>
                </span>
              </label>
              <label className="flex items-start gap-2 text-sm">
                <input type="checkbox" {...register("export_only")} className="mt-1" />
                <span>
                  Solo exportar
                  <span className="block text-xs text-muted-foreground">
                    No descarga archivos; prepara el export del chat.
                  </span>
                </span>
              </label>
            </div>
          </Card>

          <Card className="p-5">
            <h2 className="font-semibold">Plantilla</h2>
            <p className="text-xs text-muted-foreground">Aplica filtros guardados.</p>
            <Select
              aria-label="Plantilla guardada"
              className="mt-3"
              value={templateId}
              onChange={(event) => applyTemplate(event.target.value)}
            >
              <option value="">Sin plantilla</option>
              {(templates.data ?? []).map((template) => (
                <option key={template.id} value={template.id}>
                  {template.name}
                </option>
              ))}
            </Select>
            <label className="mt-3 block">
              <span className="mb-1 block text-xs font-medium">Nombre de la plantilla</span>
              <Input value={templateName} onChange={(event) => setTemplateName(event.target.value)} maxLength={120} autoComplete="off" />
            </label>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button type="button" variant="outline" size="sm" disabled={saveTemplate.isPending} onClick={() => saveTemplate.mutate("POST")}>Guardar nueva</Button>
              {templateId ? <>
                <Button type="button" variant="outline" size="sm" disabled={saveTemplate.isPending} onClick={() => saveTemplate.mutate("PUT")}>Actualizar plantilla</Button>
                <Button type="button" variant="ghost" size="sm" onClick={() => setDeleteTemplateOpen(true)}>Eliminar plantilla</Button>
              </> : null}
            </div>
          </Card>

          <Button type="submit" size="lg" className="w-full" disabled={isSubmitting}>
            {isSubmitting ? "Creando job…" : "Crear descarga"}
          </Button>
          <p className="text-center text-xs text-muted-foreground">
            El job se ejecuta en segundo plano; puedes cerrar esta pestaña.
          </p>
        </div>
      </form>
      <ConfirmDialog open={deleteTemplateOpen} onOpenChange={setDeleteTemplateOpen}
        title="Eliminar plantilla" description="Se eliminarán los filtros guardados. Las descargas se conservarán."
        confirmLabel="Eliminar plantilla" danger busy={deleteTemplate.isPending} onConfirm={() => deleteTemplate.mutate()} />
    </>
  );
}
