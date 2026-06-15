import { apiRequest } from "./client";
import type { Post, PostPage } from "../types";

export function listPosts(params: {
  page: number;
  size: number;
  q?: string;
  post_type?: string;
  category?: string;
  sort?: string;
}) {
  const search = new URLSearchParams({
    page: String(params.page),
    size: String(params.size)
  });
  if (params.q) {
    search.set("q", params.q);
  }
  if (params.post_type) {
    search.set("post_type", params.post_type);
  }
  if (params.category) {
    search.set("category", params.category);
  }
  if (params.sort) {
    search.set("sort", params.sort);
  }
  return apiRequest<PostPage>(`/api/posts?${search.toString()}`);
}

export function getPost(postId: number) {
  return apiRequest<Post>(`/api/posts/${postId}`);
}

export function incrementPostView(postId: number) {
  return apiRequest<Post>(`/api/posts/${postId}/view`, { method: "POST" });
}

export function createPost(payload: { title: string; content: string; post_type: string; category: string }) {
  return apiRequest<Post>("/api/posts", {
    method: "POST",
    json: payload
  });
}

export function updatePost(postId: number, payload: { title: string; content: string; post_type: string; category: string }) {
  return apiRequest<Post>(`/api/posts/${postId}`, {
    method: "PUT",
    json: payload
  });
}

export function deletePost(postId: number) {
  return apiRequest<void>(`/api/posts/${postId}`, { method: "DELETE" });
}
