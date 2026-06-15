import { apiRequest } from "./client";
import type { MyCommentPage, PostPage, User } from "../types";

export function updateMe(payload: { nickname: string }) {
  return apiRequest<User>("/api/users/me", {
    method: "PATCH",
    json: payload
  });
}

export function listMyPosts(params: { page: number; size: number }) {
  const search = new URLSearchParams({
    page: String(params.page),
    size: String(params.size)
  });
  return apiRequest<PostPage>(`/api/users/me/posts?${search.toString()}`);
}

export function listMyComments(params: { page: number; size: number }) {
  const search = new URLSearchParams({
    page: String(params.page),
    size: String(params.size)
  });
  return apiRequest<MyCommentPage>(`/api/users/me/comments?${search.toString()}`);
}
