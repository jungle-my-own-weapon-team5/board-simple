import type { Metadata } from "next";

import AppShell from "@/components/AppShell";
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
