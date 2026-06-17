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

const RELATED_POSTS_CACHE_TTL_MS = 30 * 60 * 1000;

type RelatedPostsCachePayload = {
  expiresAt: number;
  postUpdatedAt: string;
  items: RelatedPost[];
};

function relatedPostsCacheKey(postId: number) {
  return `related-posts:${postId}`;
}

function removeRelatedPostsCache(postId: number) {
  try {
    window.sessionStorage.removeItem(relatedPostsCacheKey(postId));
  } catch {
    // sessionStorage may be unavailable in private mode or restricted browsers.
  }
}

function readRelatedPostsCache(postId: number, postUpdatedAt: string) {
  try {
    const raw = window.sessionStorage.getItem(relatedPostsCacheKey(postId));
    if (!raw) {
      return null;
    }

    const payload = JSON.parse(raw) as Partial<RelatedPostsCachePayload>;
    if (
      typeof payload.expiresAt !== "number" ||
      payload.expiresAt <= Date.now() ||
      payload.postUpdatedAt !== postUpdatedAt ||
      !Array.isArray(payload.items)
    ) {
      removeRelatedPostsCache(postId);
      return null;
    }

    return payload.items;
  } catch {
    removeRelatedPostsCache(postId);
    return null;
  }
}

function writeRelatedPostsCache(postId: number, postUpdatedAt: string, items: RelatedPost[]) {
  try {
    const payload: RelatedPostsCachePayload = {
      expiresAt: Date.now() + RELATED_POSTS_CACHE_TTL_MS,
      postUpdatedAt,
      items
    };
    window.sessionStorage.setItem(relatedPostsCacheKey(postId), JSON.stringify(payload));
  } catch {
    // Cache writes are best-effort; related posts should still render normally.
  }
}

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
  const postUpdatedAt = post?.updated_at;
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
    if (!Number.isFinite(numericPostId) || !postUpdatedAt) {
      return;
    }
    setRelatedPosts([]);

    const cachedRelatedPosts = readRelatedPostsCache(numericPostId, postUpdatedAt);
    if (cachedRelatedPosts) {
      setRelatedPosts(cachedRelatedPosts);
      setIsRelatedLoading(false);
      return;
    }

    let isActive = true;
    setIsRelatedLoading(true);
    postApi
      .getRelatedPosts(numericPostId)
      .then((items) => {
        if (!isActive) {
          return;
        }
        setRelatedPosts(items);
        writeRelatedPostsCache(numericPostId, postUpdatedAt, items);
      })
      .catch(() => {
        if (isActive) {
          setRelatedPosts([]);
        }
      })
      .finally(() => {
        if (isActive) {
          setIsRelatedLoading(false);
        }
      });

    return () => {
      isActive = false;
    };
  }, [numericPostId, postUpdatedAt]);

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
