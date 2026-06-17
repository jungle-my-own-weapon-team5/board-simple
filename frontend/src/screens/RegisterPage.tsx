"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { useAuthStore } from "../stores/authStore";

export default function RegisterPage() {
  const router = useRouter();
  const { register } = useAuthStore();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [nickname, setNickname] = useState("");
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    try {
      await register(email, password, nickname);
      router.push("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "회원가입에 실패했습니다.");
    }
  };

  return (
    <section className="mx-auto grid min-h-[62vh] w-full max-w-md place-items-center">
      <div className="bal-card relative w-full overflow-hidden border border-border bg-card p-6 shadow-[0_18px_40px_-32px_rgba(28,27,27,0.45)]">
        <div className="mb-6 border-b border-border/70 pb-4">
          <p className="text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">History Board</p>
          <h1 className="font-serif-display mt-2 text-3xl font-bold leading-[1.35]">회원가입</h1>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">닉네임을 정하고 조선의 맥락에 참여하세요.</p>
        </div>
        <div className="space-y-4">
          <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
            <label className="flex flex-col gap-2 text-sm font-semibold">
              <span>이메일</span>
              <Input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </label>
            <label className="flex flex-col gap-2 text-sm font-semibold">
              <span>비밀번호</span>
              <Input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                minLength={8}
                required
              />
            </label>
            <label className="flex flex-col gap-2 text-sm font-semibold">
              <span>닉네임</span>
              <Input
                value={nickname}
                onChange={(event) => setNickname(event.target.value)}
                placeholder="비워두면 익명0000 형식으로 생성됩니다."
              />
            </label>
            {error ? <p className="font-semibold text-destructive">{error}</p> : null}
            <Button type="submit" className="rounded-sm">가입하기</Button>
          </form>
          <p className="text-sm text-muted-foreground">
            이미 계정이 있으면 <Link href="/login" className="font-semibold text-primary">로그인</Link>
          </p>
        </div>
      </div>
    </section>
  );
}
