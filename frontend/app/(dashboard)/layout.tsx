import { redirect } from "next/navigation";

import { auth } from "@/auth";
import { AppShell } from "@/components/shell";
import { SessionActivity } from "@/components/session-activity";

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const session = await auth();
  if (!session?.user || session.error) redirect("/login");
  if (session.user.mustChangePassword) redirect("/change-password");
  return (
    <AppShell
      user={{
        name: session.user.name,
        email: session.user.email,
        groups: session.user.groups,
      }}
    >
      <SessionActivity />
      {children}
    </AppShell>
  );
}
