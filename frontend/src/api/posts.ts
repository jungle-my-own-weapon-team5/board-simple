import { apiRequest } from "./client";
import type { Post, PostPage, ThumbnailCandidatesResponse } from "../types";

const POST_LIST_CACHE_TTL_MS = 15_000;
const POST_DETAIL_CACHE_TTL_MS = 10_000;

export type PostPayload = {
  title: string;
  content: string;
  post_type: string;
  category: string;
  tags: string[];
  thumbnail_url?: string | null;
};

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
  return apiRequest<PostPage>(`/api/posts?${search.toString()}`, {
    cacheTtlMs: POST_LIST_CACHE_TTL_MS,
  });
}

export function getPost(postId: number) {
  return apiRequest<Post>(`/api/posts/${postId}`, {
    cacheTtlMs: POST_DETAIL_CACHE_TTL_MS,
  });
}

export function incrementPostView(postId: number) {
  return apiRequest<Post>(`/api/posts/${postId}/view`, { method: "POST" });
}

export function generatePostThumbnail(postId: number) {
  return apiRequest<Post>(`/api/posts/${postId}/thumbnail`, { method: "POST" });
}

export function generatePostThumbnailCandidates(postId: number) {
  return apiRequest<ThumbnailCandidatesResponse>(`/api/posts/${postId}/thumbnail/candidates`, { method: "POST" });
}

export function generateDraftThumbnailCandidates(payload: Pick<PostPayload, "title" | "content" | "category" | "tags">) {
  return apiRequest<ThumbnailCandidatesResponse>("/api/posts/thumbnail/candidates", {
    method: "POST",
    json: payload
  });
}

export function selectPostThumbnail(postId: number, imageUrl: string) {
  return apiRequest<Post>(`/api/posts/${postId}/thumbnail`, {
    method: "PATCH",
    json: { image_url: imageUrl }
  });
}

export function uploadPostImage(file: File) {
  const formData = new FormData();
  formData.set("image", file);
  return apiRequest<{ image_url: string }>("/api/posts/uploads/images", {
    method: "POST",
    body: formData
  });
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
