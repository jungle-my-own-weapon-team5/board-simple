import { apiRequest } from "./client";
import type { DiscussionTopic, ThumbnailPreviewResponse } from "../types";

export function previewThumbnail(payload: {
  title: string;
  content: string;
  category: string;
  tags: string[];
}) {
  return apiRequest<ThumbnailPreviewResponse>("/api/admin/thumbnail/preview", {
    method: "POST",
    json: payload
  });
}

export function listDiscussionTopics(params: { topic_date?: string } = {}) {
  const search = new URLSearchParams();
  if (params.topic_date) {
    search.set("topic_date", params.topic_date);
  }
  const suffix = search.toString() ? `?${search.toString()}` : "";
  return apiRequest<DiscussionTopic[]>(`/api/admin/discussion-topics${suffix}`);
}

export function refreshDiscussionTopics(payload: { topic_date?: string | null }) {
  return apiRequest<DiscussionTopic[]>("/api/admin/discussion-topics/refresh", {
    method: "POST",
    json: payload
  });
}

export function updateDiscussionTopic(topicId: number, payload: {
  source?: string;
  title?: string;
  summary?: string;
  question?: string;
  reason?: string;
  tags?: string[];
  draft_title?: string;
  draft_content?: string;
  draft_post_type?: string;
  draft_category?: string;
  is_pinned?: boolean;
  is_hidden?: boolean;
}) {
  return apiRequest<DiscussionTopic>(`/api/admin/discussion-topics/${topicId}`, {
    method: "PATCH",
    json: payload
  });
}
