"use client";

import { ExternalLink, PenLine, Search } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useRef, useState } from "react";
import * as aiApi from "../api/ai";
import { getAssetUrl } from "../api/client";
import * as postApi from "../api/posts";
import Pagination from "../components/Pagination";
import TagChip from "../components/TagChip";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
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

export default function PostListPage() {
  const { query, page, size, setQuery, setPage } = usePostStore();
  const [draftQuery, setDraftQuery] = useState(query);
  const [data, setData] = useState<PostPage | null>(null);
  const [topics, setTopics] = useState<DiscussionTopic[]>([]);
  const [postType, setPostType] = useState("");
  const [category, setCategory] = useState("");
  const [sort, setSort] = useState("latest");
  const [error, setError] = useState<string | null>(null);
  const [searchNonce, setSearchNonce] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const resultsRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    setError(null);
    setIsLoading(true);
    postApi
      .listPosts({ page, size, q: query, post_type: postType, category, sort })
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "게시글을 불러오지 못했습니다."))
      .finally(() => setIsLoading(false));
  }, [category, page, postType, query, searchNonce, size, sort]);

  useEffect(() => {
    aiApi.listDiscussionTopics().then(setTopics).catch(() => setTopics([]));
  }, []);

  const handleSearch = (event: FormEvent) => {
    event.preventDefault();
    setPage(1);
    setQuery(draftQuery.trim());
    setSearchNonce((current) => current + 1);
    window.setTimeout(() => {
      resultsRef.current?.scrollIntoView({ block: "start", behavior: "smooth" });
    }, 0);
  };

  const resetFilters = () => {
    setDraftQuery("");
    setQuery("");
    setPostType("");
    setCategory("");
    setSort("latest");
    setPage(1);
  };

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-col items-start justify-between gap-4 md:flex-row">
        <div>
          <h1 className="text-3xl font-extrabold leading-tight sm:text-4xl">역사 덕담</h1>
          <p className="text-sm text-muted-foreground">조선시대 역사 썰과 토론이 모이는 게시판</p>
        </div>
        <form className="grid w-full grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-2 md:w-auto md:min-w-96" onSubmit={handleSearch}>
          <Search size={18} className="text-muted-foreground" />
          <Input
            value={draftQuery}
            onChange={(event) => setDraftQuery(event.target.value)}
            placeholder="Search title"
          />
          <Button type="submit" variant="outline">
            Search
          </Button>
        </form>
      </div>

      <section className="border-y border-foreground/30 py-4">
        <div className="mb-3 flex items-center justify-between gap-3">
          <h2 className="text-xl font-extrabold">오늘의 토론거리</h2>
          <Badge variant="outline">날짜별 AI 추천</Badge>
        </div>
        <div className="grid gap-3 lg:grid-cols-3">
          {topics.map((topic) => (
            <Card key={topic.title}>
              <CardContent className="flex h-full flex-col gap-3 p-4">
                {shouldShowTopicSource(topic.source) ? (
                  <Badge variant="secondary" className="w-fit">{topic.source}</Badge>
                ) : null}
                <h3 className="text-lg font-extrabold leading-snug">{topic.title}</h3>
                <p className="text-sm text-muted-foreground">{topic.summary}</p>
                <p className="border-l-2 border-primary pl-3 text-sm font-semibold">{topic.question}</p>
                <p className="text-xs text-muted-foreground">{topic.reason}</p>
                {topic.citations.length > 0 ? (
                  <div className="flex flex-col gap-2 border-t border-border pt-3">
                    <p className="text-xs font-bold">추천 근거</p>
                    {topic.citations.slice(0, 2).map((citation) => (
                      <a
                        key={citation.id}
                        href={citation.source_url || "#"}
                        target="_blank"
                        rel="noreferrer"
                        className="rounded-md border border-border bg-background p-2 text-xs hover:bg-accent"
                      >
                        <span className="flex items-center gap-1 font-semibold">
                          <ExternalLink size={13} />
                          {citation.title}
                        </span>
                        <span className="mt-1 block text-muted-foreground">
                          {citation.period} · 관련도 {citation.relevance}
                        </span>
                      </a>
                    ))}
                  </div>
                ) : null}
                <div className="mt-auto flex flex-wrap gap-2">
                  {topic.tags.map((tag) => <Badge key={tag} variant="outline">{tag}</Badge>)}
                </div>
                <Button asChild variant="outline" size="sm" className="w-fit">
                  <Link href={topicDraftHref(topic)}>
                    <PenLine size={15} />
                    <span>초안으로 글쓰기</span>
                  </Link>
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      </section>

      <div className="flex flex-wrap gap-2">
        {["", "질문", "토론", "발견", "사료 해석 요청", "가벼운 썰"].map((option) => (
          <Button key={option || "all"} type="button" variant={postType === option ? "default" : "outline"} onClick={() => {
            setPostType(option);
            setPage(1);
          }}>
            {option || "전체"}
          </Button>
        ))}
        <select className="h-10 rounded-md border border-input bg-card px-3 text-sm" value={category} onChange={(event) => {
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
        <select className="h-10 rounded-md border border-input bg-card px-3 text-sm" value={sort} onChange={(event) => {
          setSort(event.target.value);
          setPage(1);
        }}>
          <option value="latest">최신순</option>
          <option value="comments">댓글 많은 순</option>
          <option value="ai">AI 근거 있는 글</option>
        </select>
        <Button type="button" variant="outline" onClick={resetFilters}>
          필터 초기화
        </Button>
      </div>

      <div ref={resultsRef} className="scroll-mt-24">
        {error ? <p className="font-semibold text-destructive">{error}</p> : null}
      </div>
      <div className="flex flex-col gap-3">
        {isLoading ? <p className="text-sm text-muted-foreground">검색 중...</p> : null}
        {data && data.items.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col gap-3 p-6">
              <p className="font-semibold">조건에 맞는 게시글이 없습니다.</p>
              <p className="text-sm text-muted-foreground">검색어 또는 필터를 줄여 다시 확인해 보세요.</p>
              <Button type="button" variant="outline" className="w-fit" onClick={resetFilters}>
                필터 초기화
              </Button>
            </CardContent>
          </Card>
        ) : null}
        {data?.items.map((post) => (
          <Card key={post.id}>
            <CardContent className="flex flex-col justify-between gap-4 p-4 md:flex-row md:items-start">
              <div className="flex min-w-0 flex-1 flex-col gap-3 sm:flex-row">
                {post.thumbnail_url ? (
                  <Link href={`/posts/${post.id}`} className="block shrink-0 overflow-hidden border border-border bg-muted sm:w-40">
                    <img
                      src={getAssetUrl(post.thumbnail_url)}
                      alt={`${post.title} 썸네일`}
                      className="aspect-[16/9] w-full object-cover sm:h-24"
                    />
                  </Link>
                ) : null}
                <div className="min-w-0">
                <div className="mb-2 flex flex-wrap gap-2">
                  <Badge>{post.post_type}</Badge>
                  <Badge variant="outline">{post.category}</Badge>
                  <Badge variant="secondary">{post.has_ai_evidence ? "근거 있음" : "AI 미확인"}</Badge>
                </div>
                <Link href={`/posts/${post.id}`} className="inline-block text-lg font-extrabold [overflow-wrap:anywhere] hover:text-primary">
                  {post.title}
                </Link>
                <p className="text-sm text-muted-foreground">
                  {post.author.nickname} · 댓글 {post.comment_count} · 조회 {post.view_count} · {new Date(post.created_at).toLocaleDateString()}
                </p>
                </div>
              </div>
              <div className="flex shrink-0 flex-wrap gap-2 md:max-w-64 md:justify-end">
                {post.tags.map((tag) => (
                  <TagChip key={tag.id} name={tag.name} compact />
                ))}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
      {data ? (
        <Pagination page={page} size={size} total={data.total} onPageChange={setPage} />
      ) : null}
    </section>
  );
}
