"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Download,
  LayoutDashboard,
  LogOut,
  MessagesSquare,
  Moon,
  ScrollText,
  Search,
  Settings,
  Sun,
  UserRound,
} from "lucide-react";
import { signOut } from "next-auth/react";
import { useTheme } from "next-themes";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useSyncExternalStore, type ReactNode } from "react";

import { apiFetch } from "@/lib/api";
import { queryKeys } from "@/lib/query-keys";
import { cn } from "@/lib/utils";
import type { Status } from "@/lib/types";

const navItems = [
  { href: "/", label: "Resumen", icon: LayoutDashboard },
  { href: "/downloads", label: "Descargas", icon: Download },
  { href: "/chats", label: "Chats", icon: MessagesSquare },
  { href: "/logs", label: "Registros", icon: ScrollText },
  { href: "/settings", label: "Configuración", icon: Settings },
];

function Brand() {
  return (
    <Link href="/" className="flex items-center gap-2.5" aria-label="TDL Console">
      <span className="grid h-9 w-9 place-items-center rounded-xl bg-primary text-sm font-bold text-primary-foreground">
        T
      </span>
      <span className="leading-tight">
        <strong className="block text-sm">TDL Console</strong>
        <small className="hidden text-[11px] text-muted-foreground sm:block">Telegram media operations</small>
      </span>
    </Link>
  );
}

function StatusChip() {
  const { data, isError } = useQuery({
    queryKey: queryKeys.status,
    queryFn: () => apiFetch<Status>("/api/v1/status"),
    refetchInterval: 30_000,
    retry: 0,
  });
  let tone = "bg-slate-400";
  let label = "Comprobando";
  if (isError) {
    tone = "bg-red-500";
    label = "Sin conexión";
  } else if (data) {
    const ok = data.session_active && data.redis_connected && data.worker_connected;
    const warn = data.session_active || data.redis_connected;
    tone = ok ? "bg-emerald-500" : warn ? "bg-amber-500" : "bg-red-500";
    label = ok ? "Operativo" : warn ? "Atención" : "Sin sesión";
  }
  return (
    <span
      className="hidden items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-xs text-muted-foreground sm:inline-flex"
      role="status"
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", tone)} aria-hidden="true" />
      {label}
    </span>
  );
}

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  const mounted = useSyncExternalStore(
    () => () => undefined,
    () => true,
    () => false,
  );
  if (!mounted) return <span className="h-9 w-9" />;
  const dark = resolvedTheme === "dark";
  return (
    <button
      type="button"
      className="grid h-9 w-9 place-items-center rounded-lg border border-border bg-card text-muted-foreground hover:text-foreground"
      onClick={() => setTheme(dark ? "light" : "dark")}
      aria-label={dark ? "Usar tema claro" : "Usar tema oscuro"}
    >
      {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </button>
  );
}

function UserMenu({ user }: { user: { name?: string | null; email?: string | null; groups?: string[] } }) {
  const initials = (user.name ?? user.email ?? "A").slice(0, 1).toUpperCase();
  return (
    <details className="relative">
      <summary aria-label="Menú de usuario" className="flex cursor-pointer list-none items-center gap-2 rounded-lg border border-border bg-card px-2.5 py-1.5 text-sm">
        <span className="grid h-6 w-6 place-items-center rounded-full bg-secondary text-[11px] font-semibold text-secondary-foreground">
          {initials}
        </span>
        <span className="hidden max-w-32 truncate sm:block">{user.name ?? user.email ?? "Admin"}</span>
      </summary>
      <div className="absolute right-0 z-30 mt-2 w-64 rounded-xl border border-border bg-card p-3 shadow-xl">
        <div className="flex items-center gap-2 border-b border-border pb-3">
          <UserRound className="h-4 w-4 text-muted-foreground" />
          <div className="min-w-0">
            <p className="truncate text-sm font-medium">{user.name ?? "Administrador"}</p>
            <p className="truncate text-xs text-muted-foreground">{user.email ?? ""}</p>
          </div>
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground">
          {user.groups?.length ? user.groups.join(", ") : "Sesión de Authentik"}
        </p>
        <button
          type="button"
          onClick={() => signOut({ callbackUrl: "/signed-out" })}
          className="mt-3 flex w-full items-center gap-2 rounded-lg px-2 py-2 text-sm text-destructive hover:bg-destructive/10"
        >
          <LogOut className="h-4 w-4" />
          Cerrar sesión
        </button>
      </div>
    </details>
  );
}

function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="hidden border-r border-border bg-card/60 p-4 lg:flex lg:flex-col">
      <Brand />
      <nav className="mt-8 space-y-1" aria-label="Navegación principal">
        {navItems.map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors",
                active
                  ? "bg-secondary text-secondary-foreground"
                  : "text-muted-foreground hover:bg-muted hover:text-foreground",
              )}
              aria-current={active ? "page" : undefined}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
      <div className="mt-auto rounded-lg border border-border bg-background/60 p-3 text-[11px] text-muted-foreground">
        <p className="font-medium text-foreground">Un solo operador</p>
        <p className="mt-1">Descargas, sesión y cola en un panel.</p>
      </div>
    </aside>
  );
}

function Topbar({ user }: { user: { name?: string | null; email?: string | null; groups?: string[] } }) {
  return (
    <header className="sticky top-0 z-20 border-b border-border bg-background/85 backdrop-blur">
      <div className="mx-auto flex h-16 max-w-[1280px] items-center gap-3 px-4 sm:px-6 lg:px-8">
        <div className="lg:hidden">
          <Brand />
        </div>
        <form action="/search" className="ml-auto hidden w-full max-w-sm items-center gap-2 sm:flex">
          <label className="relative w-full">
            <span className="sr-only">Buscar chats, jobs y archivos</span>
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <input
              name="q"
              type="search"
              placeholder="Buscar chats, jobs y archivos"
              className="h-9 w-full rounded-lg border border-border bg-card pl-9 pr-3 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
            />
          </label>
        </form>
        <div className="ml-auto flex items-center gap-2 sm:ml-0">
          <Link href="/search" aria-label="Buscar" className="grid h-9 w-9 place-items-center rounded-lg border border-border bg-card text-muted-foreground hover:text-foreground sm:hidden">
            <Search className="h-4 w-4" aria-hidden="true" />
          </Link>
          <StatusChip />
          <ThemeToggle />
          <UserMenu user={user} />
        </div>
      </div>
    </header>
  );
}

function MobileNav() {
  const pathname = usePathname();
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-30 border-t border-border bg-card/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
      aria-label="Navegación móvil"
    >
      <div className="grid grid-cols-5">
        {navItems.map((item) => {
          const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex flex-col items-center gap-1 py-2.5 text-[11px]",
                active ? "text-primary" : "text-muted-foreground",
              )}
              aria-current={active ? "page" : undefined}
            >
              <Icon className="h-5 w-5" />
              {item.label}
            </Link>
          );
        })}
      </div>
    </nav>
  );
}

export function AppShell({
  user,
  children,
}: {
  user: { name?: string | null; email?: string | null; groups?: string[] };
  children: ReactNode;
}) {
  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[248px_1fr]">
      <a href="#main-content" className="sr-only z-50 rounded-lg bg-card p-3 text-primary focus:not-sr-only focus:fixed focus:left-4 focus:top-4">
        Saltar al contenido
      </a>
      <Sidebar />
      <div className="min-w-0">
        <Topbar user={user} />
        <main id="main-content" tabIndex={-1} className="mx-auto w-full max-w-[1280px] scroll-mt-20 px-4 pb-24 pt-6 sm:px-6 lg:px-8">
          {children}
        </main>
      </div>
      <MobileNav />
    </div>
  );
}
