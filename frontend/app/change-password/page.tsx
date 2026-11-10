import { auth } from "@/auth";
import { PasswordForm } from "@/components/auth-forms";
import { redirect } from "next/navigation";

export default async function ChangePasswordPage() {
  const session = await auth();
  if (!session?.user || session.error) redirect("/login");
  return <main className="mx-auto min-h-screen max-w-md px-6 py-16"><h1 className="text-2xl font-semibold">Cambiar contraseña</h1><p className="mt-2 text-sm text-muted-foreground">{session.user.mustChangePassword ? "Debes cambiar tu contraseña temporal antes de continuar." : "Actualiza tu contraseña de TDL Console."}</p><PasswordForm /></main>;
}
