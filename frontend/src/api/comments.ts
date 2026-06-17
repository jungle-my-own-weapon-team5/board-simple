import { apiRequest } from "./client";
import type { Comment, CommentPage } from "../types";

const COMMENT_PAGE_CACHE_TTL_MS = 10_000;

export function listComments(
  postId: number,
  params: { offset: number; limit: number }
) {
  const search = new URLSearchParams({
    offset: String(params.offset),
    limit: String(params.limit)
  });
  return apiRequest<CommentPage>(`/api/posts/${postId}/comments?${search.toString()}`, {
    cacheTtlMs: COMMENT_PAGE_CACHE_TTL_MS,
  });
}

export function createComment(postId: number, payload: { content: string }) {
  return apiRequest<Comment>(`/api/posts/${postId}/comments`, {
    method: "POST",
    json: payload
  });
}

export function updateComment(commentId: number, payload: { content: string }) {
  return apiRequest<Comment>(`/api/comments/${commentId}`, {
    method: "PUT",
    json: payload
  });
}

export function deleteComment(commentId: number) {
  return apiRequest<void>(`/api/comments/${commentId}`, { method: "DELETE" });
}
