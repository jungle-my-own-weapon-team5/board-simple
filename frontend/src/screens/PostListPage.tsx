"use client";

import { ArrowRight, BookOpen, Bot, ExternalLink, Eye, Link2, MessageCircle, PenLine, RotateCcw, Search, Share2, SlidersHorizontal, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import * as aiApi from "../api/ai";
import { getAssetUrl } from "../api/client";
import * as postApi from "../api/posts";
import Pagination from "../components/Pagination";
import TagChip from "../components/TagChip";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Input } from "../components/ui/input";
import { usePostStore } from "../stores/postStore";
import type { DiscussionTopic, PostPage } from "../types";

function topicDraftHref(topic: DiscussionTopic) {
  const search = new URLSearchParams();
  search.set("draftTitle", topic.draft_title || topic.title);
  search.set("draftContent", topic.draft_content || `${topic.summary}\n\n${topic.question}`);
  search.set("draftPostType", topic.draft_post_type || "토론");
  search.set("draftCategory", topic.draft_category || "오늘의 떡밥");
  if (topic.tags.length > 0) {
    search.set("draftTags", topic.tags.join(","));
  }
  if (topic.id) {
    search.set("topicId", String(topic.id));
  }
  return `/posts/new?${search.toString()}`;
}

function shouldShowTopicSource(source: string) {
  const normalizedSource = source.replace(/[\u200B-\u200D\uFEFF]/g, "").trim().toLowerCase();
  return !/^post[\s_-]*id\s*:/.test(normalizedSource);
}

function authorInitial(name: string) {
  return name.trim().slice(0, 1) || "덕";
}

function postFallbackLetter(title: string) {
  return title.trim().slice(0, 1) || "史";
}

export default function PostListPage() {
  const { query, page, size, setQuery, setPage } = usePostStore();
  const [draftQuery, setDraftQuery] = useState(query);
  const [data, setData] = useState<PostPage | null>(null);
  const [topics, setTopics] = useState<DiscussionTopic[]>([]);
  const [postType, setPostType] = useState("");
  const [category, setCategory] = useState("");
  const [sort, setSort] = useState("latest");
  const [error, setError] = useState<string | null>(null);
  const [isAiNoticeOpen, setIsAiNoticeOpen] = useState(false);

  useEffect(() => {
    setError(null);
    postApi
      .listPosts({ page, size, q: query, post_type: postType, category, sort })
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "게시글을 불러오지 못했습니다."));
  }, [category, page, postType, query, size, sort]);

  useEffect(() => {
    aiApi.listDiscussionTopics().then(setTopics).catch(() => setTopics([]));
  }, []);

  useEffect(() => {
    if (!isAiNoticeOpen) {
      return;
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsAiNoticeOpen(false);
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [isAiNoticeOpen]);

  const handleSearch = (event: FormEvent) => {
    event.preventDefault();
    setQuery(draftQuery.trim());
  };

  const resetFilters = () => {
    setDraftQuery("");
    setQuery("");
    setPostType("");
    setCategory("");
    setSort("latest");
    setPage(1);
  };

  const copyTopicLink = async (topic: DiscussionTopic) => {
    const url = `${window.location.origin}${topicDraftHref(topic)}`;
    await navigator.clipboard.writeText(url);
  };

  const shareTopic = async (topic: DiscussionTopic) => {
    const url = `${window.location.origin}${topicDraftHref(topic)}`;
    if (navigator.share) {
      await navigator.share({ title: topic.title, text: topic.question, url });
      return;
    }
    await navigator.clipboard.writeText(url);
  };

  return (
    <section className="min-h-screen bg-background text-foreground">
      <header className="relative overflow-hidden bg-background px-4 pb-12 pt-20 text-center sm:px-6 md:pb-16 md:pt-28">
        <div className="hero-obongdo absolute inset-0" aria-hidden="true" />
        <div className="hero-bal-mask absolute inset-y-0 right-0 hidden w-1/2 opacity-[0.035] md:block" />
        <div className="relative z-10 mx-auto max-w-7xl">
          <h1 className="font-serif-display text-5xl font-bold tracking-normal sm:text-6xl md:text-7xl">역사 덕담</h1>
          <p className="font-serif-display mt-4 text-xl font-normal text-muted-foreground md:text-3xl">
            조선시대 역사 썰과 토론이 모이는 게시판
          </p>

          <form className="mx-auto mt-10 max-w-2xl" onSubmit={handleSearch}>
            <div className="bal-focus relative">
              <Input
                value={draftQuery}
                onChange={(event) => setDraftQuery(event.target.value)}
                placeholder="사료의 행간을 검색해보세요..."
                className="h-14 rounded-sm border-border/70 bg-card px-5 pr-12 text-base shadow-none transition-all focus-visible:ring-1 focus-visible:ring-primary/30 md:h-16 md:text-lg"
              />
              <Search className="absolute right-4 top-1/2 size-5 -translate-y-1/2 text-muted-foreground" />
            </div>
          </form>

          <div className="mt-6 flex flex-col justify-center gap-3 px-4 sm:flex-row">
            <Button asChild className="h-12 rounded-sm border border-primary bg-primary px-10 text-primary-foreground hover:bg-transparent hover:text-primary">
              <Link href="/posts/new">
                <PenLine />
                <span>글쓰기</span>
              </Link>
            </Button>
            <Button asChild variant="outline" className="h-12 rounded-sm border-border/80 bg-transparent px-10 hover:border-primary hover:bg-transparent">
              <a href="#today-topics">
                <span>오늘의 토론 보기</span>
                <ArrowRight />
              </a>
            </Button>
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-7xl grid-cols-12 gap-y-12 px-4 pb-16 sm:px-6 lg:gap-x-8">
        <section id="today-topics" className="col-span-12">
          <div className="mb-6 flex items-center gap-3">
            <span className="shimmer-ai inline-flex items-center gap-2 rounded-sm px-4 py-1.5 text-xs font-bold uppercase tracking-[0.18em] text-white">
              <Sparkles className="size-4" />
              날짜별 AI 추천
            </span>
            <div className="h-px flex-1 bg-border/60" />
          </div>

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
            {topics.map((topic, index) => (
              <article
                key={topic.title}
                className="bal-card group relative flex h-full flex-col overflow-hidden border border-border/60 bg-card p-6 transition-all duration-500 hover:-translate-y-1 hover:border-primary/25 hover:shadow-[0_18px_40px_-28px_rgba(28,27,27,0.55)] md:p-7"
              >
                <div className={`absolute left-0 top-0 h-full w-1 opacity-30 transition-opacity group-hover:opacity-100 ${index === 0 ? "bg-secondary" : index === 1 ? "bg-primary" : "bg-muted-foreground"}`} />
                <div className="mb-4 flex flex-wrap items-center gap-2">
                  <span className={`${index === 1 ? "bg-secondary" : "bg-primary"} px-2 py-1 text-[10px] font-bold uppercase tracking-normal text-primary-foreground`}>
                    {index === 0 ? "검증된 사료" : index === 1 ? "뜨거운 토론" : "새 발견"}
                  </span>
                  {shouldShowTopicSource(topic.source) ? (
                    <span className="text-xs font-medium text-muted-foreground">{topic.source}</span>
                  ) : null}
                </div>
                <h3 className="font-serif-display mb-4 text-xl font-bold leading-8 transition-colors group-hover:text-secondary md:text-2xl">
                  {topic.title}
                </h3>
                <p className="mb-5 line-clamp-3 flex-1 text-sm leading-7 text-muted-foreground md:text-base">
                  {topic.summary}
                </p>
                <div className="mb-4 border-t border-border/50 pt-4">
                  <p className="font-serif-display text-base font-bold leading-8 text-primary">
                    "{topic.question}"
                  </p>
                </div>
                <p className="mb-4 text-sm leading-7 text-muted-foreground">{topic.reason}</p>
                {topic.citations.length > 0 ? (
                  <div className="mb-4 flex flex-col gap-2">
                    {topic.citations.slice(0, 1).map((citation) => (
                      <a
                        key={citation.id}
                        href={citation.source_url || "#"}
                        target="_blank"
                        rel="noreferrer"
                        className="flex items-start gap-2 border border-border/50 bg-background/70 p-2 text-xs transition-colors hover:border-secondary/60 hover:bg-accent"
                      >
                        <ExternalLink className="mt-0.5 size-3.5 shrink-0" />
                        <span>
                          <span className="block font-bold">{citation.title}</span>
                          <span className="text-muted-foreground">{citation.period} · 관련도 {citation.relevance}</span>
                        </span>
                      </a>
                    ))}
                  </div>
                ) : null}
                <div className="mb-5 flex flex-wrap gap-2">
                  {topic.tags.map((tag) => <Badge key={tag} variant="outline" className="rounded-sm bg-background/60">{tag}</Badge>)}
                </div>
                <div className="mt-auto flex items-center justify-between gap-3">
                  <div className="flex gap-2 text-muted-foreground">
                    <button
                      type="button"
                      className="grid size-8 place-items-center border border-transparent transition-colors hover:border-border hover:bg-accent hover:text-primary"
                      title="초안 링크 복사"
                      onClick={() => void copyTopicLink(topic)}
                    >
                      <Link2 className="size-4" />
                    </button>
                    <button
                      type="button"
                      className="grid size-8 place-items-center border border-transparent transition-colors hover:border-border hover:bg-accent hover:text-primary"
                      title="토론거리 공유"
                      onClick={() => void shareTopic(topic)}
                    >
                      <Share2 className="size-4" />
                    </button>
                  </div>
                  <Button asChild variant="outline" size="sm" className="rounded-sm border-secondary text-secondary hover:bg-secondary hover:text-primary-foreground">
                    <Link href={topicDraftHref(topic)}>
                      <PenLine size={15} />
                      <span>초안으로 글쓰기</span>
                    </Link>
                  </Button>
                </div>
              </article>
            ))}
          </div>
        </section>

        <aside className="col-span-12 h-fit space-y-6 bg-accent/60 p-5 md:col-span-3 lg:p-6">
          <div className="space-y-4">
            <h2 className="font-serif-display flex items-center justify-between border-b border-border/70 pb-2 text-lg font-bold text-muted-foreground">
              주제 분류
              <SlidersHorizontal className="size-4" />
            </h2>
            <div className="flex flex-wrap gap-2 md:flex-col">
              {["", "질문", "토론", "발견", "사료 해석 요청", "가벼운 썰"].map((option) => (
                <button key={option || "all"} type="button" className={`flex items-center justify-between text-left font-serif-display text-base transition-colors hover:text-secondary ${postType === option ? "font-bold text-secondary" : "text-primary"}`} onClick={() => {
                  setPostType(option);
                  setPage(1);
                }}>
                  <span>{option || "전체"}</span>
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-3">
            <label className="block text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">카테고리</label>
            <select className="h-11 w-full rounded-sm border border-border bg-card px-3 text-sm" value={category} onChange={(event) => {
              setCategory(event.target.value);
              setPage(1);
            }}>
              <option value="">모든 카테고리</option>
              <option value="왕과 권력">왕과 권력</option>
              <option value="붕당과 정치">붕당과 정치</option>
              <option value="전쟁과 외교">전쟁과 외교</option>
              <option value="인물 열전">인물 열전</option>
              <option value="생활사와 문화">생활사와 문화</option>
              <option value="사건 사고">사건 사고</option>
              <option value="사료 발견">사료 발견</option>
              <option value="오늘의 떡밥">오늘의 떡밥</option>
            </select>
          </div>

          <div className="space-y-3">
            <label className="block text-xs font-bold uppercase tracking-[0.18em] text-muted-foreground">정렬</label>
            <select className="h-11 w-full rounded-sm border border-border bg-card px-3 text-sm" value={sort} onChange={(event) => {
              setSort(event.target.value);
              setPage(1);
            }}>
              <option value="latest">최신순</option>
              <option value="comments">댓글 많은 순</option>
            </select>
          </div>

          <Button type="button" variant="outline" className="w-full rounded-sm bg-card" onClick={resetFilters}>
            <RotateCcw />
            <span>필터 초기화</span>
          </Button>

          <div className="bal-card relative overflow-hidden border border-border/60 bg-card p-4">
            <h3 className="font-serif-display mb-2 text-lg font-bold">사료 해석 도움이 필요하신가요?</h3>
            <p className="mb-4 text-sm leading-6 text-muted-foreground">
              AI Archivist가 한문 사료와 역사적 맥락을 함께 짚어드립니다.
            </p>
            <Button type="button" className="w-full rounded-sm bg-primary text-primary-foreground hover:bg-secondary" onClick={() => setIsAiNoticeOpen(true)}>
              AI 상담소 가기
            </Button>
          </div>
        </aside>

        <section className="col-span-12 space-y-6 md:col-span-9">
          <div className="flex flex-col justify-between gap-4 border-b border-border/70 pb-3 sm:flex-row sm:items-center">
            <h2 className="font-serif-display text-3xl font-bold">최신 토론 목록</h2>
            <div className="flex gap-4 overflow-x-auto pb-1 text-sm font-bold">
              <button type="button" className={sort === "latest" ? "border-b-2 border-primary text-primary" : "text-muted-foreground hover:text-primary"} onClick={() => setSort("latest")}>최신순</button>
              <button type="button" className={sort === "comments" ? "border-b-2 border-primary text-primary" : "text-muted-foreground hover:text-primary"} onClick={() => setSort("comments")}>댓글 많은 순</button>
            </div>
          </div>

          {error ? <p className="font-semibold text-destructive">{error}</p> : null}
          {data && data.items.length === 0 ? (
            <div className="border border-border bg-card p-8">
              <p className="font-serif-display text-xl font-bold">조건에 맞는 게시글이 없습니다.</p>
              <p className="mt-2 text-sm text-muted-foreground">검색어 또는 필터를 줄여 다시 확인해 보세요.</p>
              <Button type="button" variant="outline" className="mt-4 w-fit rounded-sm" onClick={resetFilters}>
                필터 초기화
              </Button>
            </div>
          ) : null}

          <div className="flex flex-col gap-4">
            {data?.items.map((post) => (
              <article key={post.id} className="bal-card group relative flex flex-col gap-4 overflow-hidden border border-border/50 bg-card p-4 transition-all hover:border-primary/30 md:flex-row md:gap-6">
                <Link href={`/posts/${post.id}`} className="relative h-36 w-full shrink-0 overflow-hidden bg-accent md:h-auto md:w-48">
                  {post.thumbnail_url ? (
                    <img
                      src={getAssetUrl(post.thumbnail_url)}
                      alt={`${post.title} 썸네일`}
                      className="h-full w-full object-cover transition-transform duration-500 group-hover:scale-105"
                    />
                  ) : (
                    <div className="flex h-full w-full items-center justify-center overflow-hidden">
                      <span className="font-serif-display absolute -bottom-5 -right-2 text-8xl font-bold text-primary opacity-[0.05]">{postFallbackLetter(post.title)}</span>
                      <BookOpen className="size-9 text-muted-foreground/45" />
                    </div>
                  )}
                </Link>
                <div className="flex min-w-0 flex-1 flex-col justify-between gap-4">
                  <div>
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <span className="bg-accent px-2 py-1 text-[10px] font-bold uppercase tracking-normal text-muted-foreground">{post.category}</span>
                      <Badge className="rounded-sm">{post.post_type}</Badge>
                    </div>
                    <Link href={`/posts/${post.id}`} className="font-serif-display inline-block text-xl font-bold leading-8 [overflow-wrap:anywhere] transition-colors hover:text-secondary">
                      {post.title}
                    </Link>
                  </div>
                  <div className="flex flex-col justify-between gap-3 border-t border-border/50 pt-3 lg:flex-row lg:items-center">
                    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                      <span className="grid size-6 place-items-center rounded-full bg-accent text-[10px] font-bold text-primary">
                        {authorInitial(post.author.nickname)}
                      </span>
                      <span className="font-bold text-primary">{post.author.nickname}</span>
                      <span>{new Date(post.created_at).toLocaleDateString()}</span>
                      <span className="inline-flex items-center gap-1"><MessageCircle className="size-3.5" />{post.comment_count}</span>
                      <span className="inline-flex items-center gap-1"><Eye className="size-3.5" />{post.view_count}</span>
                    </div>
                    <div className="flex shrink-0 flex-wrap gap-2 lg:max-w-72 lg:justify-end">
                      {post.tags.map((tag) => (
                        <TagChip key={tag.id} name={tag.name} compact />
                      ))}
                    </div>
                  </div>
                </div>
              </article>
            ))}
          </div>
          {data ? (
            <Pagination page={page} size={size} total={data.total} onPageChange={setPage} />
          ) : null}
        </section>
      </div>

      {isAiNoticeOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-primary/35 px-4 backdrop-blur-sm"
          role="presentation"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) {
              setIsAiNoticeOpen(false);
            }
          }}
        >
          <section
            role="dialog"
            aria-modal="true"
            aria-labelledby="ai-notice-title"
            className="relative w-full max-w-sm border border-border/80 bg-background p-6 shadow-[0_28px_80px_-34px_rgba(28,27,27,0.75)]"
          >
            <button
              type="button"
              className="absolute right-3 top-3 grid size-8 place-items-center rounded-sm text-muted-foreground transition-colors hover:bg-accent hover:text-primary"
              aria-label="서비스 예정 안내 닫기"
              onClick={() => setIsAiNoticeOpen(false)}
            >
              <X className="size-4" />
            </button>
            <div className="mb-5 flex items-center gap-3">
              <span className="grid size-10 place-items-center rounded-full bg-secondary/15 text-secondary">
                <Bot className="size-5" />
              </span>
              <div>
                <p className="text-[11px] font-bold uppercase tracking-[0.18em] text-muted-foreground">Archivist AI</p>
                <h2 id="ai-notice-title" className="font-serif-display text-2xl font-bold leading-tight">서비스 예정입니다</h2>
              </div>
            </div>
            <p className="text-sm leading-6 text-muted-foreground">
              AI 상담소는 사료 해석과 역사적 맥락을 더 안정적으로 제공하기 위해 준비 중입니다. 곧 게시판 안에서 바로 사용할 수 있게 열어두겠습니다.
            </p>
            <div className="mt-6 flex justify-end gap-2">
              <Button type="button" variant="ghost" className="rounded-sm" onClick={() => setIsAiNoticeOpen(false)}>
                닫기
              </Button>
              <Button asChild className="rounded-sm bg-primary text-primary-foreground hover:bg-primary/90">
                <Link href="/posts/new">글쓰기 먼저 하기</Link>
              </Button>
            </div>
          </section>
        </div>
      ) : null}
    </section>
  );
}
