export default async function SignedOutPage({ searchParams }: { searchParams: Promise<{ error?: string }> }) {
  const failed = Boolean((await searchParams).error);
  return (
    <main className="grid min-h-screen place-items-center p-6">
      <section className="max-w-md space-y-4">
        <h1 className="text-2xl font-semibold">{failed ? "No se pudo iniciar sesión" : "Sesión de TDL cerrada"}</h1>
        <p className="text-muted-foreground">
          {failed
            ? "Authentik no completó el acceso. Puedes reintentarlo o consultar al administrador si el problema continúa."
            : "Tu sesión de Authentik puede seguir activa. Si compartes este equipo, cierra también la sesión en Authentik."}
        </p>
        <a href="/login" className="inline-block rounded-lg bg-primary px-4 py-2 text-primary-foreground focus-visible:outline-2 focus-visible:outline-offset-4">
          {failed ? "Reintentar con Authentik" : "Volver a entrar con Authentik"}
        </a>
      </section>
    </main>
  );
}
