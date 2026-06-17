"use client";

import { Search, SlidersHorizontal, X } from "lucide-react";
import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import * as postApi from "../api/posts";
import Pagination from "../components/Pagination";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { usePostStore } from "../stores/postStore";
import type { PostPage } from "../types";

export default function PostListPage() {
  const { query, contentQuery, tag, page, size, setFilters, setPage } = usePostStore();
  const [draftQuery, setDraftQuery] = useState(query);
  const [draftContentQuery, setDraftContentQuery] = useState(contentQuery);
  const [draftTag, setDraftTag] = useState(tag);
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const [data, setData] = useState<PostPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    postApi
      .listPosts({ page, size, q: query, content_q: contentQuery, tag })
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "게시글을 불러오지 못했습니다."));
  }, [contentQuery, page, query, size, tag]);

  const handleSearch = (event: FormEvent) => {
    event.preventDefault();
    setFilters({
      query: draftQuery.trim(),
      contentQuery: draftContentQuery.trim(),
      tag: draftTag.trim().replace(/^#/, "").toLowerCase(),
    });
  };

  const clearFilters = () => {
    setDraftQuery("");
    setDraftContentQuery("");
    setDraftTag("");
    setFilters({ query: "", contentQuery: "", tag: "" });
  };

  const hasFilters = Boolean(query || contentQuery || tag);

  return (
    <section className="flex flex-col gap-5">
      <div className="flex flex-col items-start justify-between gap-4 md:flex-row">
        <div>
          <h1 className="text-3xl font-extrabold leading-tight sm:text-4xl">Posts</h1>
          <p className="text-sm text-muted-foreground">제목 검색과 페이지네이션을 지원합니다.</p>
        </div>
        <form className="flex w-full flex-col gap-2 md:w-auto md:min-w-96" onSubmit={handleSearch}>
          <div className="grid grid-cols-[auto_minmax(0,1fr)_auto_auto] items-center gap-2">
            <Search size={18} className="text-muted-foreground" />
            <Input
              value={draftQuery}
              onChange={(event) => setDraftQuery(event.target.value)}
              placeholder="Search title"
            />
            <Button
              type="button"
              variant={isFilterOpen ? "secondary" : "outline"}
              size="icon"
              aria-label="검색 필터"
              onClick={() => setIsFilterOpen((current) => !current)}
            >
              <SlidersHorizontal />
            </Button>
            <Button type="submit" variant="outline">
              Search
            </Button>
          </div>
          {isFilterOpen ? (
            <div className="grid gap-2 rounded-md border border-border bg-card p-3 md:grid-cols-2">
              <Input
                value={draftContentQuery}
                onChange={(event) => setDraftContentQuery(event.target.value)}
                placeholder="Search body"
              />
              <Input
                value={draftTag}
                onChange={(event) => setDraftTag(event.target.value)}
                placeholder="Tag"
              />
            </div>
          ) : null}
          {hasFilters ? (
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              {query ? <Badge variant="secondary">title: {query}</Badge> : null}
              {contentQuery ? <Badge variant="secondary">body: {contentQuery}</Badge> : null}
              {tag ? <Badge variant="secondary">#{tag}</Badge> : null}
              <Button type="button" variant="ghost" size="sm" onClick={clearFilters}>
                <X />
                <span>Clear</span>
              </Button>
            </div>
          ) : null}
        </form>
      </div>

      {error ? <p className="font-semibold text-destructive">{error}</p> : null}
      <div className="flex flex-col gap-3">
        {data?.items.map((post) => (
          <Card key={post.id}>
            <CardContent className="flex flex-col justify-between gap-4 p-4 md:flex-row md:items-start">
              <div className="min-w-0">
                <Link href={`/posts/${post.id}`} className="inline-block text-lg font-extrabold [overflow-wrap:anywhere] hover:text-primary">
                  {post.title}
                </Link>
                <p className="text-sm text-muted-foreground">
                  {post.author.nickname} · {new Date(post.created_at).toLocaleDateString()}
                </p>
              </div>
              <div className="flex flex-wrap gap-2">
                {post.tags.map((tag) => (
                  <Badge variant="secondary" key={tag.id}>
                    #{tag.name}
                  </Badge>
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
