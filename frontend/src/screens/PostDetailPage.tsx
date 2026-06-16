"use client";

import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import { Pencil, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import * as postApi from "../api/posts";
import CommentList from "../components/CommentList";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { useAuthStore } from "../stores/authStore";
import type { Post, RelatedPost } from "../types";

export default function PostDetailPage() {
  const router = useRouter();
  const params = useParams<{ postId: string }>();
  const postId = params.postId;
  const { user } = useAuthStore();
  const [post, setPost] = useState<Post | null>(null);
  const [relatedPosts, setRelatedPosts] = useState<RelatedPost[]>([]);
  const [isRelatedLoading, setIsRelatedLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const numericPostId = Number(postId);
  const isAuthor = user && post && user.id === post.author.id;

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

  useEffect(() => {
    if (!Number.isFinite(numericPostId)) {
      return;
    }
    setRelatedPosts([]);
    setIsRelatedLoading(true);
    postApi
      .getRelatedPosts(numericPostId)
      .then(setRelatedPosts)
      .catch(() => setRelatedPosts([]))
      .finally(() => setIsRelatedLoading(false));
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
    <article className="flex flex-col gap-5">
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
      <section className="markdown-body border-y border-border py-5">
        <ReactMarkdown rehypePlugins={[rehypeSanitize]}>{post.content}</ReactMarkdown>
      </section>
      {isRelatedLoading || relatedPosts.length ? (
        <section className="flex flex-col gap-3 border-b border-border pb-5">
          <h2 className="text-xl font-extrabold">연관 글</h2>
          {isRelatedLoading ? (
            <p className="text-sm text-muted-foreground">연관 글을 불러오는 중...</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {relatedPosts.map((relatedPost) => (
                <li key={relatedPost.post_id}>
                  <Link
                    href={`/posts/${relatedPost.post_id}`}
                    className="font-semibold [overflow-wrap:anywhere] hover:text-primary"
                  >
                    {relatedPost.title}
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}
      <CommentList postId={post.id} />
    </article>
  );
}
