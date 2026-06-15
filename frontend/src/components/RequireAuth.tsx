"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { useAuthStore } from "@/stores/authStore";

export default function RequireAuth({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { isLoading, user } = useAuthStore();

  if (isLoading) {
    return <p className="text-muted-foreground">Loading...</p>;
  }

  if (!user) {
    return (
      <section className="mx-auto max-w-md">
        <Card>
          <CardHeader>
            <CardTitle>Login required</CardTitle>
          </CardHeader>
          <CardContent className="grid gap-4">
            <p className="text-sm text-muted-foreground">
              FitLog stores goals, meals, reports, and strategy advice per user. Sign in before using it.
            </p>
            <Button asChild>
              <Link href={`/login?next=${encodeURIComponent(pathname)}`}>Login</Link>
            </Button>
          </CardContent>
        </Card>
      </section>
    );
  }

  return <>{children}</>;
}
