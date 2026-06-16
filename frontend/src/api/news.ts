import { apiRequest } from "./client";
import type {
  HackerNewsImportResponse,
  HackerNewsPreviewItem,
  HackerNewsPreviewResponse,
  HackerNewsSource,
} from "../types";

export function previewHackerNews(params: {
  source: HackerNewsSource;
  query?: string;
  limit: number;
}) {
  return apiRequest<HackerNewsPreviewResponse>("/api/news/hacker-news/preview", {
    method: "POST",
    json: params,
  });
}

export function importHackerNews(items: HackerNewsPreviewItem[]) {
  return apiRequest<HackerNewsImportResponse>("/api/news/hacker-news/import", {
    method: "POST",
    json: {
      items: items.map((item) => ({
        hn_id: item.hn_id,
        title: item.title,
        url: item.url,
        hn_url: item.hn_url,
        summary: item.summary,
        key_points: item.key_points,
      })),
    },
  });
}
