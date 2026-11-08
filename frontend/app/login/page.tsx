import { Download, ShieldCheck } from "lucide-react";
import { authentikEnabled } from "@/auth";
import { LoginForm } from "@/components/auth-forms";

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ changed?: string; error?: string }> }) {
  const params = await searchParams;
  return (
    <main className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden overflow-hidden border-r border-border bg-card p-12 lg:flex lg:flex-col lg:justify-between">
        <div className="surface-grid absolute inset-0 opacity-60" aria-hidden="true" />
        <div className="relative">
          <div className="flex items-center gap-3"><span className="grid h-10 w-10 place-items-center rounded-xl bg-primary text-sm font-bold text-primary-foreground">T</span><div><p className="text-sm font-semibold">TDL Console</p><p className="text-xs text-muted-foreground">Telegram media operations</p></div></div>
          <h1 className="mt-16 max-w-lg text-4xl font-semibold leading-tight tracking-tight">Descargas de Telegram, sin sorpresas.</h1>
          <p className="mt-4 max-w-md text-sm leading-6 text-muted-foreground">Exporta, filtra y descarga media con seguimiento real. Una consola para el operador.</p>
        </div>
        <div className="relative grid gap-3 text-sm text-muted-foreground"><div className="flex items-center gap-2"><Download className="h-4 w-4 text-primary" aria-hidden="true" />Jobs reanudables y progreso verificable.</div><div className="flex items-center gap-2"><ShieldCheck className="h-4 w-4 text-primary" aria-hidden="true" />Acceso local y sesión protegida.</div></div>
      </section>
      <section className="flex items-center justify-center p-6 sm:p-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-3 lg:hidden"><span className="grid h-10 w-10 place-items-center rounded-xl bg-primary text-sm font-bold text-primary-foreground">T</span><div><p className="text-sm font-semibold">TDL Console</p><p className="text-xs text-muted-foreground">Telegram media operations</p></div></div>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Acceso de operador</p>
          <h2 className="mt-2 text-2xl font-semibold tracking-tight">Inicia sesión</h2>
          <p className="mt-2 text-sm text-muted-foreground">Usa tu usuario y contraseña de TDL Console.</p>
          {params.changed && <p role="status" className="mt-4 text-sm">Contraseña actualizada. Inicia sesión de nuevo.</p>}
          {params.error && <p role="alert" className="mt-4 text-sm text-destructive">No se pudo iniciar sesión. Intenta de nuevo o usa tu cuenta local.</p>}
          <LoginForm external={authentikEnabled()} />
          <p className="mt-4 text-xs text-muted-foreground">Si no tienes acceso, pide una cuenta al administrador.</p>
        </div>
      </section>
    </main>
  );
}
