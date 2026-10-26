/* eslint-disable @next/next/no-img-element */
"use client";

import { Download, ExternalLink, FileText } from "lucide-react";

import { Badge, Card } from "@/components/ui";
import type { EventItem, JobFile } from "@/lib/types";

export function FileGrid({ files }: { files: JobFile[] }) {
  if (!files.length) {
    return (
      <p className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-muted-foreground">
        No hay archivos descargados todavía.
      </p>
    );
  }
  return (
    <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
      {files.map((file) => (
        <Card key={file.relative_path} className="overflow-hidden">
          <div className="grid h-40 place-items-center bg-muted">
            {file.kind === "image" ? (
              <img
                src={file.content_url}
                alt={file.name}
                loading="lazy"
                className="h-full w-full object-cover"
              />
            ) : file.kind === "video" ? (
              <video src={file.content_url} controls preload="metadata" className="h-full w-full" />
            ) : file.kind === "audio" ? (
              <audio src={file.content_url} controls preload="metadata" className="w-full px-4" />
            ) : (
              <FileText className="h-10 w-10 text-muted-foreground" aria-hidden="true" />
            )}
          </div>
          <div className="space-y-2 p-3">
            <div className="flex items-start justify-between gap-2">
              <p className="truncate text-sm font-medium" title={file.relative_path}>
                {file.name}
              </p>
              <Badge variant="outline">{file.kind}</Badge>
            </div>
            <p className="text-xs text-muted-foreground">
              {file.human_size} · {file.modified_label}
            </p>
            <div className="flex items-center gap-2">
              <a
                href={file.download_url}
                className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted"
              >
                <Download className="h-3.5 w-3.5" />
                Descargar
              </a>
              {file.can_preview ? (
                <a
                  href={file.content_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-muted"
                >
                  <ExternalLink className="h-3.5 w-3.5" />
                  Ver
                </a>
              ) : null}
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}

export function LogViewer({ content, truncated }: { content: string; truncated: boolean }) {
  return (
    <div className="space-y-2">
      {truncated ? (
        <p className="text-xs text-amber-600 dark:text-amber-400">
          Mostrando solo el final del log.
        </p>
      ) : null}
      <pre className="max-h-96 overflow-auto rounded-lg border border-border bg-slate-950 p-4 text-xs leading-5 text-slate-200">
        {content || "Sin registros todavía."}
      </pre>
    </div>
  );
}

export function EventTimeline({ events }: { events: EventItem[] }) {
  if (!events.length) {
    return <p className="text-sm text-muted-foreground">Sin eventos todavía.</p>;
  }
  return (
    <ol className="space-y-3">
      {events.map((event, index) => (
        <li key={`${event.timestamp}-${index}`} className="flex gap-3">
          <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary" aria-hidden="true" />
          <div>
            <p className="text-sm font-medium">{event.title}</p>
            <p className="text-xs text-muted-foreground">{event.message}</p>
            {event.timestamp ? (
              <p className="mono mt-0.5 text-[11px] text-muted-foreground">{event.timestamp}</p>
            ) : null}
          </div>
        </li>
      ))}
    </ol>
  );
}
