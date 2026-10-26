import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { AppShell } from "@/components/shell";

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();
  if (!session?.user || session.error) redirect("/login");
  return (
    <AppShell
      user={{
        name: session.user.name,
        email: session.user.email,
        groups: session.user.groups,
      }}
    >
      {children}
    </AppShell>
  );
}
