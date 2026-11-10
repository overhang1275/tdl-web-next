"use client";
import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { apiFetch } from "@/lib/api";

export function SessionActivity() {
  const path = usePathname();
  const last = useRef(0);
  const [unavailable, setUnavailable] = useState(false);
  useEffect(() => {
    const record = () => {
      if (Date.now() - last.current < 60_000) return;
      last.current = Date.now();
      void apiFetch("/api/session/activity", { method: "POST" }).then(() => setUnavailable(false)).catch(() => setUnavailable(true));
    };
    record();
    document.addEventListener("click", record);
    document.addEventListener("keydown", record);
    return () => { document.removeEventListener("click", record); document.removeEventListener("keydown", record); };
  }, [path]);
  return unavailable ? <p role="status" className="border-b border-border bg-card p-3 text-sm">No se pudo verificar la sesión. Intenta de nuevo al continuar.</p> : null;
}
