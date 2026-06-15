import type { Metadata } from "next";

import AppShell from "@/components/AppShell";
import "highlight.js/styles/github-dark.css";
import "katex/dist/katex.min.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "Board Simple",
  description: "A simple markdown board",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
