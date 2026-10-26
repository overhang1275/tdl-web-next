import Link from "next/link";

export default function NotFound() {
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-3 p-6 text-center">
      <p className="mono text-xs text-muted-foreground">404</p>
      <h1 className="text-2xl font-semibold">Ruta no encontrada</h1>
      <p className="text-sm text-muted-foreground">
        La página que buscas no existe o cambió de lugar.
      </p>
      <Link
        href="/"
        className="mt-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground"
      >
        Volver al resumen
      </Link>
    </main>
  );
}
