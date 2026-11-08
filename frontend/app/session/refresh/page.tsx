"use client";
import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui";

function Refresh() {
  const params = useSearchParams();
  const [error, setError] = useState(false);
  function refresh() {
    return apiFetch("/api/session/refresh", { method: "POST" }).then(() => {
      const target = new URL(params.get("returnTo") ?? "/", window.location.origin);
      window.location.assign(target.origin === window.location.origin ? target.href : window.location.origin);
    }).catch(() => setError(true));
  }
  useEffect(() => { void refresh(); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return <main className="mx-auto max-w-md p-8"><h1 className="text-xl font-semibold">Verificando sesión</h1><p role="status" className="my-4">{error ? "No se pudo verificar la sesión. Intenta de nuevo." : "Un momento…"}</p>{error && <Button onClick={() => { setError(false); void refresh(); }}>Reintentar</Button>}</main>;
}
export default function RefreshPage() { return <Suspense><Refresh /></Suspense>; }
