"use client";

import { Bot, BookOpen, FlaskConical, Lightbulb, LogIn, LogOut, PenLine, ShieldCheck, UserPlus } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import AiChatWidget from "@/components/AiChatWidget";
import { Button } from "@/components/ui/button";
import { useAuthStore } from "@/stores/authStore";

type AppShellProps = {
  children: React.ReactNode;
};

function nicknameInitial(nickname: string) {
  return nickname.trim().slice(0, 1) || "덕";
}

export default function AppShell({ children }: AppShellProps) {
  const router = useRouter();
  const pathname = usePathname();
  const { bootstrap, isLoading, user, logout } = useAuthStore();
  const isAdmin = user?.is_admin ?? false;
  const isHome = pathname === "/";

  useEffect(() => {
    void bootstrap();
  }, [bootstrap]);

  const handleLogout = async () => {
    await logout();
    router.push("/");
  };

  const handleOpenAiChat = () => {
    window.dispatchEvent(new Event("history-board:open-ai-chat"));
  };

  if (isLoading) {
    return (
      <div className="grid min-h-screen place-items-center bg-background">
        <div className="border border-border bg-card px-6 py-4 text-sm font-semibold text-muted-foreground">
          화면을 준비하는 중입니다.
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-border/45 bg-background/90 px-4 py-3 backdrop-blur-md sm:px-6">
        <div className="mx-auto grid max-w-7xl grid-cols-[auto_1fr_auto] items-center gap-4">
          <Link href="/" className="group flex items-center gap-3" aria-label="역사 덕담 홈">
            <span className="grid size-9 place-items-center bg-accent text-[9px] font-bold leading-none text-primary transition-colors group-hover:bg-primary group-hover:text-primary-foreground">
              역사<br />덕담
            </span>
            <span className="font-serif-display text-2xl font-bold tracking-normal text-primary sm:text-3xl">
              역사 덕담
            </span>
          </Link>
          <nav className="hidden min-w-0 flex-wrap items-center gap-2 text-sm font-bold tracking-[0.05em] md:flex">
            <Button
              asChild
              variant="ghost"
              size="sm"
              className={`rounded-sm ${isHome ? "bg-accent text-primary" : "text-muted-foreground hover:text-primary"}`}
            >
              <Link href="/">
                <BookOpen />
                <span>게시판</span>
              </Link>
            </Button>
            <Button type="button" variant="ghost" size="sm" className="rounded-sm text-muted-foreground hover:text-primary" onClick={handleOpenAiChat}>
              <Bot />
              <span>AI 챗봇</span>
            </Button>
            {isAdmin ? (
              <Button asChild variant="ghost" size="sm" className="rounded-sm text-muted-foreground hover:text-primary">
                <Link href="/ai/playground">
                  <FlaskConical />
                  <span>AI 실험실</span>
                </Link>
              </Button>
            ) : null}
            {isAdmin ? (
              <>
                <Button asChild variant="ghost" size="sm" className="rounded-sm text-muted-foreground hover:text-primary">
                  <Link href="/admin/discussion-topics">
                    <Lightbulb />
                    <span>토론거리 관리</span>
                  </Link>
                </Button>
                <Button asChild variant="ghost" size="sm" className="rounded-sm text-muted-foreground hover:text-primary">
                  <Link href="/admin/thumbnail">
                    <ShieldCheck />
                    <span>썸네일 실험실</span>
                  </Link>
                </Button>
              </>
            ) : null}
          </nav>
          <nav className="hidden items-center justify-end gap-3 text-sm font-bold md:flex">
            {user ? (
              <>
                <Link
                  href="/me"
                  aria-label="내 정보"
                  className="group flex items-center gap-2 border border-transparent px-2 py-1.5 transition-colors hover:border-border/70 hover:bg-accent/70"
                >
                  <span className="grid size-8 place-items-center rounded-full border border-border/70 bg-card font-serif-display text-sm font-bold text-primary transition-colors group-hover:border-secondary/40 group-hover:text-secondary">
                    {nicknameInitial(user.nickname)}
                  </span>
                  <span className="flex max-w-32 flex-col text-left leading-none">
                    <span className="truncate text-sm font-bold text-primary">{user.nickname}</span>
                    <span className="mt-1 text-[10px] font-bold uppercase tracking-[0.12em] text-muted-foreground">
                      {isAdmin ? "관리자" : "덕담러"}
                    </span>
                  </span>
                </Link>
                <Button asChild size="sm" className="rounded-sm bg-primary px-5 text-primary-foreground hover:bg-primary/85">
                  <Link href="/posts/new">
                    <PenLine />
                    <span>글쓰기</span>
                  </Link>
                </Button>
                <Button type="button" variant="ghost" size="sm" className="rounded-sm text-muted-foreground hover:text-primary" onClick={handleLogout}>
                  <LogOut />
                  <span>로그아웃</span>
                </Button>
              </>
            ) : (
              <>
                <Button asChild variant="ghost" size="sm" className="rounded-sm text-muted-foreground hover:text-primary">
                  <Link href="/login">
                    <LogIn />
                    <span>로그인</span>
                  </Link>
                </Button>
                <Button asChild variant="ghost" size="sm" className="rounded-sm text-muted-foreground hover:text-primary">
                  <Link href="/register">
                    <UserPlus />
                    <span>회원가입</span>
                  </Link>
                </Button>
              </>
            )}
          </nav>
          <div className="flex items-center gap-2 md:hidden">
            <Button asChild variant="ghost" size="icon" className="rounded-sm" title="게시판">
              <Link href="/"><BookOpen /></Link>
            </Button>
            <Button type="button" variant="ghost" size="icon" className="rounded-sm" title="AI 챗봇" onClick={handleOpenAiChat}>
              <Bot />
            </Button>
            <Button asChild variant="ghost" size="icon" className="rounded-sm" title="글쓰기">
              <Link href="/posts/new"><PenLine /></Link>
            </Button>
          </div>
        </div>
      </header>
      <main className={isHome ? "w-full" : "mx-auto w-full max-w-7xl px-4 py-8 sm:px-6 lg:px-8"}>
        {children}
      </main>
      <AiChatWidget />
    </div>
  );
}
