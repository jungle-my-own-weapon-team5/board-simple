import { apiRequest } from "./client";
import type { ThumbnailPreviewResponse } from "../types";

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
