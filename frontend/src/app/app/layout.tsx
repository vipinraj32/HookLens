import { Providers } from "@/components/providers";
import { AppShell } from "@/components/shell";

export default function AppLayout({ children }: LayoutProps<"/app">) {
  return (
    <Providers>
      <AppShell>{children}</AppShell>
    </Providers>
  );
}
