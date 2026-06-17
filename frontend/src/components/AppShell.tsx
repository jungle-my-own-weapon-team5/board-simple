"use client";

import { LogIn, LogOut, PanelRightClose, PanelRightOpen, PenLine, UserPlus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import AgentPanel from "@/components/AgentPanel";
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
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className={
                isAgentOpen
                  ? "ml-2 h-9 w-9 rounded-md border border-primary bg-primary text-primary-foreground shadow-sm hover:bg-primary/90 hover:text-primary-foreground"
                  : "ml-2 h-9 w-9 rounded-md border border-border bg-muted text-foreground shadow-sm hover:bg-accent"
              }
              title="Toggle right sidebar"
              aria-label="Toggle right sidebar"
              aria-pressed={isAgentOpen}
              onClick={() => setIsAgentOpen((current) => !current)}
            >
              {isAgentOpen ? <PanelRightClose /> : <PanelRightOpen />}
            </Button>
          </nav>
        </div>
      </header>
      <div className="flex min-h-[calc(100vh-61px)]">
        <main className="min-w-0 flex-1 px-4 py-8 sm:px-6 lg:px-8">
          <div className="mx-auto w-full max-w-5xl">{children}</div>
        </main>
        <AgentPanel
          isAuthenticated={Boolean(user)}
          isOpen={isAgentOpen}
          onClose={() => setIsAgentOpen(false)}
        />
      </div>
    </div>
  );
}
