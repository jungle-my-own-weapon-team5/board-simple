"use client";

import { ImagePlus, Loader2 } from "lucide-react";
import { useState } from "react";

import * as adminApi from "@/api/admin";
import { ApiError, getAssetUrl } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useAuthStore } from "@/stores/authStore";
import type { ThumbnailPreviewResponse } from "@/types";

export default function AdminThumbnailPage() {
  const { user } = useAuthStore();
  const [title, setTitle] = useState("양녕대군 고양이 사건, 너무 사소해서 더 기억남");
  const [category, setCategory] = useState("왕실 TMI");
  const [tags, setTags] = useState("양녕대군, 고양이, 왕실TMI");
  const [content, setContent] = useState(
    "양녕대군이 남의 금빛 고양이를 탐냈다는 이야기를 보는데, 큰 정치 사건보다 이런 장면이 더 오래 기억납니다.\n\n폐세자 이미지가 워낙 강해서 그런지, 그냥 철없는 왕족의 일화인지 성격을 보여주는 단서인지 애매하네요."
  );
  const [result, setResult] = useState<ThumbnailPreviewResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  const isAdmin = user?.is_admin ?? false;

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError(null);
    setResult(null);

    try {
      const response = await adminApi.previewThumbnail({
        title: title.trim(),
        category: category.trim(),
        content: content.trim(),
        tags: tags
          .split(",")
          .map((tag) => tag.trim().replace(/^#/, ""))
          .filter(Boolean)
      });
      setResult(response);
    } catch (requestError) {
      const message =
        requestError instanceof ApiError
          ? requestError.message
          : "썸네일 테스트 생성에 실패했습니다.";
      setError(message);
    } finally {
      setIsSubmitting(false);
    }
  };

  if (!isAdmin) {
    return (
      <section className="space-y-4">
        <h1 className="text-3xl font-extrabold leading-tight sm:text-4xl">관리자 썸네일 테스트</h1>
        <p className="text-sm text-muted-foreground">
          관리자 계정으로 로그인해야 사용할 수 있습니다.
        </p>
      </section>
    );
  }

  return (
    <section className="space-y-6">
      <header className="space-y-2">
        <h1 className="text-3xl font-extrabold leading-tight sm:text-4xl">관리자 썸네일 테스트</h1>
        <p className="text-sm text-muted-foreground">
          게시글 저장 없이 본문 기반 썸네일 생성 프롬프트와 결과 이미지를 확인합니다.
        </p>
      </header>

      <form className="grid gap-4 rounded-md border border-border bg-card p-5" onSubmit={handleSubmit}>
        <label className="grid gap-2 text-sm font-semibold">
          제목
          <Input value={title} onChange={(event) => setTitle(event.target.value)} />
        </label>
        <div className="grid gap-4 md:grid-cols-2">
          <label className="grid gap-2 text-sm font-semibold">
            카테고리
            <Input value={category} onChange={(event) => setCategory(event.target.value)} />
          </label>
          <label className="grid gap-2 text-sm font-semibold">
            태그
            <Input value={tags} onChange={(event) => setTags(event.target.value)} />
          </label>
        </div>
        <label className="grid gap-2 text-sm font-semibold">
          본문
          <Textarea
            className="min-h-48"
            value={content}
            onChange={(event) => setContent(event.target.value)}
          />
        </label>
        {error ? <p className="text-sm font-semibold text-destructive">{error}</p> : null}
        <Button type="submit" className="w-fit" disabled={isSubmitting}>
          {isSubmitting ? <Loader2 className="animate-spin" /> : <ImagePlus />}
          <span>{isSubmitting ? "생성 중" : "썸네일 테스트 생성"}</span>
        </Button>
      </form>

      {result ? (
        <section className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
          <div className="rounded-md border border-border bg-card p-4">
            <h2 className="mb-3 text-xl font-extrabold">생성 결과</h2>
            {result.image_url ? (
              <img
                src={getAssetUrl(result.image_url)}
                alt={`${title} 썸네일 미리보기`}
                className="aspect-[3/2] w-full rounded-md border border-border object-cover"
              />
            ) : (
              <div className="grid aspect-[3/2] place-items-center rounded-md border border-dashed border-border text-sm text-muted-foreground">
                생성된 이미지가 없습니다. OpenAI 키, 모델, 결제/권한 상태를 확인하세요.
              </div>
            )}
          </div>
          <div className="space-y-4">
            <div className="rounded-md border border-border bg-card p-4">
              <h2 className="mb-2 text-lg font-extrabold">Agent Brief</h2>
              <p className="whitespace-pre-wrap text-sm leading-6">{result.visual_brief}</p>
            </div>
            <div className="rounded-md border border-border bg-card p-4">
              <h2 className="mb-2 text-lg font-extrabold">최종 프롬프트</h2>
              <p className="max-h-80 overflow-auto whitespace-pre-wrap text-xs leading-5 text-muted-foreground">
                {result.prompt}
              </p>
            </div>
            <div className="rounded-md border border-border bg-card p-4 text-sm">
              <h2 className="mb-2 text-lg font-extrabold">Tool Log</h2>
              <p>
                {result.tool_log.tool} · {result.tool_log.status} · {result.tool_log.elapsed_ms}ms
              </p>
            </div>
          </div>
        </section>
      ) : null}
    </section>
  );
}
