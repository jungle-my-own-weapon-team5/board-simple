"use client";

import { useParams, usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import * as postApi from "../api/posts";
import PostForm from "../components/PostForm";
import { useAuthStore } from "../stores/authStore";
import type { Post } from "../types";

export default function PostEditorPage() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useParams<{ postId?: string }>();
  const postId = params.postId;
  const { user } = useAuthStore();
  const [post, setPost] = useState<Post | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isEditing = Boolean(postId);
  const numericPostId = Number(postId);

  useEffect(() => {
    if (!isEditing) {
      return;
    }
    postApi
      .getPost(numericPostId)
      .then(setPost)
      .catch((err) => setError(err instanceof Error ? err.message : "게시글을 불러오지 못했습니다."));
  }, [isEditing, numericPostId]);

  useEffect(() => {
    if (!user) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [pathname, router, user]);

  if (!user) {
    return <p className="text-muted-foreground">Redirecting...</p>;
  }

  if (error) {
    return <p className="font-semibold text-destructive">{error}</p>;
  }

  if (isEditing && !post) {
    return <p className="text-muted-foreground">Loading...</p>;
  }

  const handleSubmit = async (payload: { title: string; content: string; post_type: string; category: string }) => {
    const saved = isEditing
      ? await postApi.updatePost(numericPostId, payload)
      : await postApi.createPost(payload);
    router.push(`/posts/${saved.id}`);
  };

  return (
    <section className="flex flex-col gap-5">
      <h1 className="text-3xl font-extrabold leading-tight sm:text-4xl">
        {isEditing ? "Edit Post" : "Write Post"}
      </h1>
      <PostForm
        initialTitle={post?.title}
        initialContent={post?.content}
        initialPostType={post?.post_type}
        initialCategory={post?.category}
        submitLabel={isEditing ? "Update post" : "Create post"}
        onSubmit={handleSubmit}
      />
    </section>
  );
}
