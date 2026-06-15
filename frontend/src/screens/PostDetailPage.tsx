"use client";

import { Pencil, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";
import * as postApi from "../api/posts";
import CommentList from "../components/CommentList";
import MarkdownRenderer from "../components/MarkdownRenderer";
import PostTableOfContents from "../components/PostTableOfContents";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { extractMarkdownHeadings } from "../lib/markdownHeadings";
import { useAuthStore } from "../stores/authStore";
import type { Post } from "../types";

export default function PostDetailPage() {
  const router = useRouter();
  const params = useParams<{ postId: string }>();
  const postId = params.postId;
  const { user } = useAuthStore();
  const [post, setPost] = useState<Post | null>(null);
  const [error, setError] = useState<string | null>(null);

  const numericPostId = Number(postId);
  const isAuthor = user && post && user.id === post.author.id;
  const headings = useMemo(() => (post ? extractMarkdownHeadings(post.content) : []), [post]);

  useEffect(() => {
    if (!Number.isFinite(numericPostId)) {
      setError("잘못된 게시글입니다.");
      return;
    }
    postApi
      .getPost(numericPostId)
      .then(setPost)
      .catch((err) => setError(err instanceof Error ? err.message : "게시글을 불러오지 못했습니다."));
  }, [numericPostId]);

  const handleDelete = async () => {
    if (!post) {
      return;
    }
    await postApi.deletePost(post.id);
    router.push("/");
  };

  if (error) {
    return <p className="font-semibold text-destructive">{error}</p>;
  }

  if (!post) {
    return <p className="text-muted-foreground">Loading...</p>;
  }

  return (
    <>
      <article className="flex min-w-0 flex-col gap-5">
        <header className="flex flex-col items-start justify-between gap-4 md:flex-row">
          <div>
            <h1 className="break-words text-3xl font-extrabold leading-tight sm:text-4xl">
              {post.title}
            </h1>
            <p className="text-sm text-muted-foreground">
              {post.author.nickname} · {new Date(post.created_at).toLocaleString()}
            </p>
          </div>
          {isAuthor ? (
            <div className="flex flex-wrap items-center gap-2">
              <Button asChild variant="outline">
                <Link href={`/posts/${post.id}/edit`}>
                  <Pencil />
                  <span>Edit</span>
                </Link>
              </Button>
              <Button type="button" variant="destructive" onClick={handleDelete}>
                <Trash2 />
                <span>Delete</span>
              </Button>
            </div>
          ) : null}
        </header>
        <div className="flex flex-wrap gap-2">
          {post.tags.map((tag) => (
            <Badge variant="secondary" key={tag.id}>
              #{tag.name}
            </Badge>
          ))}
        </div>
        <MarkdownRenderer content={post.content} className="border-y border-border py-5" />
        <CommentList postId={post.id} />
      </article>
      <PostTableOfContents headings={headings} />
    </>
  );
}
