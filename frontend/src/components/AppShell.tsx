"use client";

import { Bot, LogIn, LogOut, PenLine, UserPlus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import AgentPanel from "@/components/AgentPanel";
import FloatingChat from "@/components/FloatingChat";
import { useAuthStore } from "@/stores/authStore";

type AppShellProps = {
  children: React.ReactNode;
};

export default function AppShell({ children }: AppShellProps) {
  const router = useRouter();
  const { bootstrap, isLoading, user, logout } = useAuthStore();
  const [isAgentOpen, setIsAgentOpen] = useState(false);

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  const handleLogout = async () => {
    await logout();
    setIsAgentOpen(false);
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
            Board Simple
          </Link>
          <nav className="flex flex-wrap items-center justify-end gap-2">
            <Button
              type="button"
              variant={isAgentOpen ? "secondary" : "outline"}
              size="sm"
              onClick={() => setIsAgentOpen((current) => !current)}
            >
              <Bot />
              <span>AI Agent</span>
            </Button>
            {user ? (
              <>
                <Badge variant="secondary" className="min-h-9 px-3">
                  {user.nickname}
                </Badge>
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
      <AgentPanel
        isAuthenticated={Boolean(user)}
        isOpen={isAgentOpen}
        onClose={() => setIsAgentOpen(false)}
      />
      {user ? <FloatingChat /> : null}
    </div>
  );
}
