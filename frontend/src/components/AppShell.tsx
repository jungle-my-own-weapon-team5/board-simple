"use client";

import { LogIn, LogOut, MessageCircle, Newspaper, PenLine, UserPlus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/authStore";

type AppShellProps = {
  children: React.ReactNode;
};

export default function AppShell({ children }: AppShellProps) {
  const router = useRouter();
  const { bootstrap, isLoading, user, logout } = useAuthStore();

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  const handleLogout = async () => {
    await logout();
    router.push("/");
  };

  if (isLoading) {
    return <div className="grid min-h-screen place-items-center">Loading...</div>;
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-border bg-card/95 px-4 py-3 backdrop-blur sm:px-8">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-4">
          <Link href="/" className="text-xl font-extrabold">
            tech news
          </Link>
          <nav className="flex flex-wrap items-center justify-end gap-2">
            <Button asChild variant="outline" size="sm">
              <Link href="/ask">
                <MessageCircle />
                <span>Q&A</span>
              </Link>
            </Button>
            {user ? (
              <>
                <Badge variant="secondary" className="min-h-9 px-3">
                  {user.nickname}
                </Badge>
                <Button asChild variant="outline" size="sm">
                  <Link href="/news/import">
                    <Newspaper />
                    <span>뉴스 수집</span>
                  </Link>
                </Button>
                <Button asChild variant="outline" size="sm">
                  <Link href="/posts/new">
                    <PenLine />
                    <span>Write</span>
                  </Link>
                </Button>
                <Button type="button" variant="outline" size="sm" onClick={handleLogout}>
                  <LogOut />
                  <span>Logout</span>
                </Button>
              </>
            ) : (
              <>
                <Button asChild variant="outline" size="sm">
                  <Link href="/login">
                    <LogIn />
                    <span>Login</span>
                  </Link>
                </Button>
                <Button asChild variant="outline" size="sm">
                  <Link href="/register">
                    <UserPlus />
                    <span>Register</span>
                  </Link>
                </Button>
              </>
            )}
          </nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6 lg:px-8">
        {children}
      </main>
    </div>
  );
}
