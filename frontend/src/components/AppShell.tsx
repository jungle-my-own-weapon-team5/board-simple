"use client";

import { FlaskConical, Lightbulb, LogIn, LogOut, PenLine, ShieldCheck, UserPlus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import AiChatWidget from "@/components/AiChatWidget";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/authStore";

type AppShellProps = {
  children: React.ReactNode;
};

export default function AppShell({ children }: AppShellProps) {
  const router = useRouter();
  const { bootstrap, isLoading, user, logout } = useAuthStore();
  const isAdmin = user?.is_admin ?? false;

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
            역사 덕담
          </Link>
          <nav className="flex flex-wrap items-center justify-end gap-2">
            {isAdmin ? (
              <Button asChild variant="outline" size="sm">
                <Link href="/ai/playground">
                  <FlaskConical />
                  <span>AI Playground</span>
                </Link>
              </Button>
            ) : null}
            {user ? (
              <>
                {isAdmin ? (
                  <>
                    <Button asChild variant="outline" size="sm">
                      <Link href="/admin/discussion-topics">
                        <Lightbulb />
                        <span>토론거리 관리</span>
                      </Link>
                    </Button>
                    <Button asChild variant="outline" size="sm">
                      <Link href="/admin/thumbnail">
                        <ShieldCheck />
                        <span>Thumbnail Lab</span>
                      </Link>
                    </Button>
                  </>
                ) : null}
                <Link href="/me" aria-label="내 정보">
                  <Badge variant="secondary" className="min-h-9 px-3">
                    {user.nickname}
                  </Badge>
                </Link>
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
      <main className="mx-auto w-full max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
        {children}
      </main>
      <AiChatWidget />
    </div>
  );
}
