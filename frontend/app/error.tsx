"use client";

import { Button } from "@/components/ui";

export default function GlobalError({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="mx-auto flex min-h-[60vh] max-w-md flex-col items-center justify-center gap-3 text-center">
      <h1 className="text-xl font-semibold">Algo salió mal</h1>
      <p className="text-sm text-muted-foreground">
        La consola no pudo completar la operación. Reintenta o vuelve al resumen.
      </p>
      <Button onClick={reset}>Reintentar</Button>
    </div>
  );
}
