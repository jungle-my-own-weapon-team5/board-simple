"use client";

import { Search } from "lucide-react";
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
  const { query, page, size, setQuery, setPage } = usePostStore();
  const [draftQuery, setDraftQuery] = useState(query);
  const [data, setData] = useState<PostPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    postApi
      .listPosts({ page, size, q: query })
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "게시글을 불러오지 못했습니다."));
  }, [page, query, size]);

  const handleSearch = (event: FormEvent) => {
    event.preventDefault();
    setQuery(draftQuery.trim());
  };

  return (
    <section className="flex flex-col gap-5">
      <div className="flex flex-col items-start justify-between gap-4 md:flex-row">
        <div>
          <h1 className="text-3xl font-extrabold leading-tight sm:text-4xl">Posts</h1>
          <p className="text-sm text-muted-foreground">제목 검색과 페이지네이션을 지원합니다.</p>
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
