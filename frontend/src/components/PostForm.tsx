"use client";

import { Sparkles, Save } from "lucide-react";
import { FormEvent, useMemo, useState } from "react";
import * as aiApi from "../api/ai";
import { ApiError } from "../api/client";
import type { WritingAssist } from "../types";
import MarkdownEditor from "./MarkdownEditor";
import { Badge } from "./ui/badge";
import { Button } from "./ui/button";
import { Input } from "./ui/input";

type PostFormProps = {
  initialTitle?: string;
  initialContent?: string;
  initialPostType?: string;
  initialCategory?: string;
  submitLabel: string;
  onSubmit: (payload: { title: string; content: string; post_type: string; category: string }) => Promise<void>;
};

const TAG_PATTERN = /#([0-9A-Za-z가-힣_]{1,50})/g;

function extractTags(content: string) {
  return Array.from(new Set([...content.matchAll(TAG_PATTERN)].map((match) => match[1].toLowerCase())));
}

function friendlyError(error: unknown) {
  if (error instanceof ApiError) {
    if (error.status === 401) {
      return "로그인이 필요합니다. 다시 로그인해 주세요.";
    }
    if (error.status === 403) {
      return "이 글을 수정하거나 삭제할 권한이 없습니다.";
    }
  }
  return error instanceof Error ? error.message : "요청을 처리하지 못했습니다.";
}

export default function PostForm({
  initialTitle = "",
  initialContent = "",
  initialPostType = "토론",
  initialCategory = "왕과 권력",
  submitLabel,
  onSubmit
}: PostFormProps) {
  const [title, setTitle] = useState(initialTitle);
  const [content, setContent] = useState(initialContent);
  const [postType, setPostType] = useState(initialPostType);
  const [category, setCategory] = useState(initialCategory);
  const [assist, setAssist] = useState<WritingAssist | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isAssisting, setIsAssisting] = useState(false);
  const tags = useMemo(() => extractTags(content), [content]);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      await onSubmit({ title, content, post_type: postType, category });
    } catch (err) {
      setError(friendlyError(err));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleAssist = async () => {
    setError(null);
    setIsAssisting(true);
    try {
      const result = await aiApi.getWritingAssist({ title, content, post_type: postType });
      setAssist(result);
      setCategory(result.category);
    } catch (err) {
      setError(err instanceof Error ? err.message : "AI 추천을 만들지 못했습니다.");
    } finally {
      setIsAssisting(false);
    }
  };

  return (
    <form className="flex flex-col gap-5" onSubmit={handleSubmit}>
      <label className="flex flex-col gap-2 text-sm font-semibold">
        <span>Title</span>
        <Input
          value={title}
          onChange={(event) => setTitle(event.target.value)}
          maxLength={200}
          required
          placeholder="제목"
        />
      </label>
      <div className="grid gap-3 md:grid-cols-2">
        <label className="flex flex-col gap-2 text-sm font-semibold">
          <span>글 유형</span>
          <select className="h-10 rounded-md border border-input bg-card px-3" value={postType} onChange={(event) => setPostType(event.target.value)}>
            {["질문", "토론", "발견", "사료 해석 요청", "가벼운 썰"].map((option) => (
              <option key={option} value={option}>{option}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-2 text-sm font-semibold">
          <span>카테고리</span>
          <select className="h-10 rounded-md border border-input bg-card px-3" value={category} onChange={(event) => setCategory(event.target.value)}>
            {["왕과 권력", "붕당과 정치", "전쟁과 외교", "인물 열전", "생활사와 문화", "사건 사고", "사료 발견", "오늘의 떡밥"].map((option) => (
              <option key={option} value={option}>{option}</option>
            ))}
          </select>
        </label>
      </div>
      <MarkdownEditor value={content} onChange={setContent} />
      <div className="flex flex-wrap gap-2">
        {tags.length === 0 ? <span className="text-sm text-muted-foreground">No tags</span> : null}
        {tags.map((tag) => (
          <Badge variant="secondary" key={tag}>
            #{tag}
          </Badge>
        ))}
      </div>
      <section className="border border-border bg-accent/40 p-4">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-base font-extrabold">AI 글쓰기 보조</h2>
            <p className="text-sm text-muted-foreground">제목, 태그, 카테고리, 토론 질문을 데모 로직으로 추천합니다.</p>
          </div>
          <Button type="button" variant="outline" onClick={handleAssist} disabled={isAssisting}>
            <Sparkles />
            <span>{isAssisting ? "추천 중..." : "추천 만들기"}</span>
          </Button>
        </div>
        {assist ? (
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            <div className="flex flex-col gap-2">
              <p className="text-sm font-bold">추천 제목</p>
              {assist.improved_titles.map((item) => (
                <Button key={item} type="button" variant="outline" className="h-auto justify-start whitespace-normal text-left" onClick={() => setTitle(item)}>
                  {item}
                </Button>
              ))}
            </div>
            <div className="flex flex-col gap-2">
              <p className="text-sm font-bold">토론 질문</p>
              {assist.questions.map((item) => (
                <p key={item} className="text-sm text-muted-foreground">{item}</p>
              ))}
            </div>
          </div>
        ) : null}
      </section>
      {error ? <p className="font-semibold text-destructive">{error}</p> : null}
      <Button type="submit" className="w-fit" disabled={isSubmitting}>
        <Save />
        <span>{isSubmitting ? "Saving..." : submitLabel}</span>
      </Button>
    </form>
  );
}
