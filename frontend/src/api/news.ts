import { apiRequest } from "./client";
import type {
  DuplicateJudgementRequestItem,
  DuplicateJudgementResponse,
  HackerNewsImportResponse,
  HackerNewsPreviewItem,
  HackerNewsPreviewResponse,
  HackerNewsSource,
  WebArticleImportResponse,
  WebArticlePreviewItem,
  WebArticlePreviewResponse,
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

export function judgeNewsDuplicates(items: DuplicateJudgementRequestItem[]) {
  return apiRequest<DuplicateJudgementResponse>("/api/news/duplicates/judge", {
    method: "POST",
    json: { items },
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

export function previewWebArticle(params: { url: string; article_text?: string }) {
  return apiRequest<WebArticlePreviewResponse>("/api/news/web/preview", {
    method: "POST",
    json: params,
  });
}

export function importWebArticles(items: WebArticlePreviewItem[]) {
  return apiRequest<WebArticleImportResponse>("/api/news/web/import", {
    method: "POST",
    json: {
      items: items.map((item) => ({
        source_type: item.source_type,
        source_id: item.source_id,
        title: item.title,
        url: item.url,
        summary: item.summary,
        key_points: item.key_points,
      })),
    },
  });
}
