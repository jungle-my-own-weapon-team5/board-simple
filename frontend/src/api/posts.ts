import { apiRequest } from "./client";
import type { Post, PostPage, RelatedPost } from "../types";

export function listPosts(params: { page: number; size: number; q?: string }) {
  const search = new URLSearchParams({
    page: String(params.page),
    size: String(params.size)
  });
  if (params.q) {
    search.set("q", params.q);
  }
  return apiRequest<PostPage>(`/api/posts?${search.toString()}`);
}

export function getPost(postId: number) {
  return apiRequest<Post>(`/api/posts/${postId}`);
}

export function getRelatedPosts(postId: number) {
  return apiRequest<RelatedPost[]>(`/api/posts/${postId}/related`);
}

export function createPost(payload: { title: string; content: string }) {
  return apiRequest<Post>("/api/posts", {
    method: "POST",
    json: payload
  });
}

export function updatePost(postId: number, payload: { title: string; content: string }) {
  return apiRequest<Post>(`/api/posts/${postId}`, {
    method: "PUT",
    json: payload
  });
}

export function deletePost(postId: number) {
  return apiRequest<void>(`/api/posts/${postId}`, { method: "DELETE" });
}
