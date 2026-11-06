import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "HookLens", template: "%s · HookLens" },
  description:
    "Open-source Uniswap v4 LP intelligence: decode hook permissions, run deterministic analyzers and fork simulations, and see what your liquidity is really exposed to.",
};

export const viewport: Viewport = {
  themeColor: "#140d1c",
  colorScheme: "dark",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full font-sans">{children}</body>
    </html>
  );
}
