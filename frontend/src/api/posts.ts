import { apiRequest } from "./client";
import type { Post, PostDuplicateCheckResponse, PostPage, PostThumbnailResponse } from "../types";

export type PostPayload = {
  title: string;
  content: string;
  tags: string[];
};

export type PostListParams = {
  page: number;
  size: number;
  q?: string;
  content_q?: string;
  tag?: string;
};

export function listPosts(params: PostListParams) {
  const search = new URLSearchParams({
    page: String(params.page),
    size: String(params.size)
  });
  if (params.q) {
    search.set("q", params.q);
  }
  if (params.content_q) {
    search.set("content_q", params.content_q);
  }
  if (params.tag) {
    search.set("tag", params.tag);
  }
  return apiRequest<PostPage>(`/api/posts?${search.toString()}`);
}

export function getPost(postId: number) {
  return apiRequest<Post>(`/api/posts/${postId}`);
}

export function createPost(payload: PostPayload) {
  return apiRequest<Post>("/api/posts", {
    method: "POST",
    json: payload
  });
}

export function updatePost(postId: number, payload: PostPayload) {
  return apiRequest<Post>(`/api/posts/${postId}`, {
    method: "PUT",
    json: payload
  });
}

export function deletePost(postId: number) {
  return apiRequest<void>(`/api/posts/${postId}`, { method: "DELETE" });
}

export function checkDuplicatePosts(payload: PostPayload & { exclude_post_id?: number }) {
  return apiRequest<PostDuplicateCheckResponse>("/api/posts/duplicate-check", {
    method: "POST",
    json: payload
  });
}

export function generateThumbnail(payload: PostPayload) {
  return apiRequest<PostThumbnailResponse>("/api/posts/generate-thumbnail", {
    method: "POST",
    json: payload
  });
}
