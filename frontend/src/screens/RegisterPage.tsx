"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { SubmitEvent } from "react";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { useAuthStore } from "../stores/authStore";

export default function RegisterPage() {
  const router = useRouter();
  const { register } = useAuthStore();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [nickname, setNickname] = useState("");
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (event: SubmitEvent<HTMLFormElement>) => {
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
    <section className="mx-auto w-full max-w-md">
      <Card>
        <CardHeader>
          <CardTitle>Register</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <form className="flex flex-col gap-4" onSubmit={handleSubmit}>
            <label className="flex flex-col gap-2 text-sm font-semibold">
              <span>Email</span>
              <Input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </label>
            <label className="flex flex-col gap-2 text-sm font-semibold">
              <span>Password</span>
              <Input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                minLength={8}
                required
              />
            </label>
            <label className="flex flex-col gap-2 text-sm font-semibold">
              <span>Nickname</span>
              <Input
                value={nickname}
                onChange={(event) => setNickname(event.target.value)}
                placeholder="비워두면 익명0000 형식으로 생성됩니다."
              />
            </label>
            {error ? <p className="font-semibold text-destructive">{error}</p> : null}
            <Button type="submit">Register</Button>
          </form>
          <p className="text-sm text-muted-foreground">
            이미 계정이 있으면 <Link href="/login" className="font-semibold text-primary">로그인</Link>
          </p>
        </CardContent>
      </Card>
    </section>
  );
}
