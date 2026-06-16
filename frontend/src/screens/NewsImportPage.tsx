"use client";

import { Check, ExternalLink, Newspaper, Search } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useState } from "react";
import * as newsApi from "../api/news";
import { Badge } from "../components/ui/badge";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Input } from "../components/ui/input";
import { useAuthStore } from "../stores/authStore";
import type {
  DuplicateMatch,
  HackerNewsImportResponse,
  HackerNewsPreviewItem,
  HackerNewsSource,
  WebArticleImportResponse,
  WebArticlePreviewItem,
} from "../types";

type NewsMode = "hacker-news" | "url";
type PreviewItem = HackerNewsPreviewItem | WebArticlePreviewItem;
type ImportResult = HackerNewsImportResponse | WebArticleImportResponse;

const SOURCE_LABELS: Record<HackerNewsSource, string> = {
  top: "Top",
  best: "Best",
  new: "New",
  search: "Search",
};

export default function NewsImportPage() {
  const router = useRouter();
  const pathname = usePathname();
  const { user } = useAuthStore();
  const [mode, setMode] = useState<NewsMode>("hacker-news");
  const [source, setSource] = useState<HackerNewsSource>("top");
  const [query, setQuery] = useState("");
  const [url, setUrl] = useState("");
  const [limit, setLimit] = useState(10);
  const [items, setItems] = useState<PreviewItem[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isImporting, setIsImporting] = useState(false);

  useEffect(() => {
    if (!user) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [pathname, router, user]);

  const selectableItems = useMemo(
    () =>
      items.filter(
        (item) =>
          item.summary_status === "success" &&
          (!isHackerNewsItem(item) || !item.is_imported) &&
          item.summary &&
          item.key_points.length,
      ),
    [items],
  );

  const selectedItems = useMemo(
    () => selectableItems.filter((item) => selectedIds.has(itemKey(item))),
    [selectableItems, selectedIds],
  );

  if (!user) {
    return <p className="text-muted-foreground">Redirecting...</p>;
  }

  const handlePreview = async (event: FormEvent) => {
    event.preventDefault();
    if (mode === "hacker-news" && source === "search" && !query.trim()) {
      setError("검색어를 입력해 주세요.");
      return;
    }
    if (mode === "url" && !url.trim()) {
      setError("기사 URL을 입력해 주세요.");
      return;
    }

    setIsPreviewing(true);
    setError(null);
    setResult(null);
    setSelectedIds(new Set());
    try {
      if (mode === "url") {
        const data = await newsApi.previewWebArticle({ url: url.trim() });
        setItems([data.item]);
      } else {
        const data = await newsApi.previewHackerNews({
          source,
          query: source === "search" ? query.trim() : undefined,
          limit,
        });
        setItems(data.items);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "뉴스 후보를 불러오지 못했습니다.");
    } finally {
      setIsPreviewing(false);
    }
  };

  const handleImport = async () => {
    if (!selectedItems.length) {
      setError("게시할 뉴스를 선택해 주세요.");
      return;
    }

    setIsImporting(true);
    setError(null);
    try {
      const importResult =
        mode === "url"
          ? await newsApi.importWebArticles(selectedItems as WebArticlePreviewItem[])
          : await newsApi.importHackerNews(selectedItems as HackerNewsPreviewItem[]);
      setResult(importResult);
      if (mode === "hacker-news") {
        const importedIds = new Set(
          (importResult as HackerNewsImportResponse).created.map((post) => post.hn_id),
        );
        setItems((current) =>
          current.map((item) =>
            isHackerNewsItem(item) && importedIds.has(item.hn_id)
              ? { ...item, is_imported: true }
              : item,
          ),
        );
      }
      setSelectedIds(new Set());
    } catch (err) {
      setError(err instanceof Error ? err.message : "선택한 뉴스를 게시하지 못했습니다.");
    } finally {
      setIsImporting(false);
    }
  };

  const toggleItem = (item: PreviewItem) => {
    if (
      item.summary_status !== "success" ||
      (isHackerNewsItem(item) && item.is_imported) ||
      !item.summary ||
      !item.key_points.length
    ) {
      return;
    }
    setSelectedIds((current) => {
      const next = new Set(current);
      const key = itemKey(item);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  return (
    <section className="flex flex-col gap-5">
      <header>
        <h1 className="text-3xl font-extrabold leading-tight sm:text-4xl">뉴스 수집</h1>
        <p className="text-sm text-muted-foreground">
          Hacker News와 웹 기사 후보를 요약한 뒤 선택한 항목만 게시합니다.
        </p>
      </header>

      <form className="flex flex-col gap-3 border-y border-border py-4" onSubmit={handlePreview}>
        <div className="flex flex-wrap gap-2">
          <Button
            type="button"
            variant={mode === "hacker-news" ? "default" : "outline"}
            onClick={() => setMode("hacker-news")}
          >
            <Newspaper />
            <span>Hacker News</span>
          </Button>
          <Button
            type="button"
            variant={mode === "url" ? "default" : "outline"}
            onClick={() => setMode("url")}
          >
            <ExternalLink />
            <span>URL</span>
          </Button>
        </div>

        {mode === "hacker-news" ? (
          <>
        <div className="flex flex-wrap gap-2">
          {(["top", "best", "new", "search"] as HackerNewsSource[]).map((value) => (
            <Button
              key={value}
              type="button"
              variant={source === value ? "default" : "outline"}
              onClick={() => setSource(value)}
            >
              {value === "search" ? <Search /> : <Newspaper />}
              <span>{SOURCE_LABELS[value]}</span>
            </Button>
          ))}
        </div>

        <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_8rem_auto]">
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="검색어"
            disabled={source !== "search"}
          />
          <Input
            type="number"
            min={1}
            max={20}
            value={limit}
            onChange={(event) => setLimit(Number(event.target.value))}
          />
          <Button type="submit" disabled={isPreviewing}>
            {isPreviewing ? "수집 중" : "후보 보기"}
          </Button>
        </div>
          </>
        ) : (
          <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
            <Input
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://example.com/article"
            />
            <Button type="submit" disabled={isPreviewing}>
              {isPreviewing ? "수집 중" : "후보 보기"}
            </Button>
          </div>
        )}
      </form>

      {error ? <p className="font-semibold text-destructive">{error}</p> : null}

      {items.length ? (
        <div className="flex items-center justify-between gap-3">
          <p className="text-sm text-muted-foreground">
            선택 가능 {selectableItems.length}개 · 선택 {selectedItems.length}개
          </p>
          <Button type="button" onClick={handleImport} disabled={isImporting || !selectedItems.length}>
            <Check />
            <span>{isImporting ? "게시 중" : "선택 항목 게시"}</span>
          </Button>
        </div>
      ) : null}

      <div className="flex flex-col gap-3">
        {items.map((item) => {
          const selectable = selectableItems.some((candidate) => itemKey(candidate) === itemKey(item));
          const checked = selectedIds.has(itemKey(item));
          return (
            <Card key={itemKey(item)}>
              <CardContent className="flex flex-col gap-4 p-4">
                <div className="flex flex-col gap-3 md:flex-row md:items-start">
                  <input
                    type="checkbox"
                    className="mt-1 size-5"
                    checked={checked}
                    disabled={!selectable}
                    onChange={() => toggleItem(item)}
                    aria-label={`${item.title} 선택`}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="text-lg font-extrabold [overflow-wrap:anywhere]">
                        {item.title}
                      </h2>
                      {isHackerNewsItem(item) && item.is_imported ? (
                        <Badge variant="secondary">가져옴</Badge>
                      ) : item.summary_status === "success" ? (
                        <Badge>요약 완료</Badge>
                      ) : (
                        <Badge variant="outline" className="text-destructive">
                          실패
                        </Badge>
                      )}
                    </div>
                    {isHackerNewsItem(item) ? (
                      <p className="text-sm text-muted-foreground">
                        {item.author ?? "unknown"} · {item.points ?? 0} points ·{" "}
                        {item.comment_count ?? 0} comments
                      </p>
                    ) : null}
                  </div>
                </div>

                {item.summary ? (
                  <p className="leading-7 [overflow-wrap:anywhere]">{item.summary}</p>
                ) : (
                  <p className="text-sm font-semibold text-destructive">
                    {item.error ?? "요약을 만들지 못했습니다."}
                  </p>
                )}

                {item.key_points.length ? (
                  <ul className="list-disc space-y-1 pl-5 text-sm leading-6 text-muted-foreground">
                    {item.key_points.map((point) => (
                      <li key={point}>{point}</li>
                    ))}
                  </ul>
                ) : null}

                {item.duplicate_matches.length ? (
                  <DuplicateMatches matches={item.duplicate_matches} />
                ) : null}

                <div className="flex flex-wrap gap-3 text-sm">
                  {item.url ? (
                    <a
                      className="inline-flex items-center gap-1 font-semibold hover:text-primary"
                      href={item.url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      원문 <ExternalLink size={14} />
                    </a>
                  ) : null}
                  {isHackerNewsItem(item) ? (
                  <a
                    className="inline-flex items-center gap-1 font-semibold hover:text-primary"
                    href={item.hn_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Hacker News <ExternalLink size={14} />
                  </a>
                  ) : null}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>

      {result ? (
        <section className="flex flex-col gap-3 border-t border-border pt-5">
          <h2 className="text-xl font-extrabold">게시 결과</h2>
          {result.created.map((post) => (
            <Link
              key={post.post_id}
              href={`/posts/${post.post_id}`}
              className="font-semibold hover:text-primary"
            >
              게시됨: {post.title}
            </Link>
          ))}
          {result.skipped.map((item) => (
            <p key={skippedKey(item)} className="text-sm text-muted-foreground">
              건너뜀: {skippedKey(item)} · {item.reason}
            </p>
          ))}
        </section>
      ) : null}
    </section>
  );
}

function DuplicateMatches({ matches }: { matches: DuplicateMatch[] }) {
  return (
    <section className="border-t border-border pt-3">
      <h3 className="text-sm font-bold">중복 의심</h3>
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-muted-foreground">
        {matches.map((match) => (
          <li key={`${match.reason}-${match.post_id}`}>
            <Link href={`/posts/${match.post_id}`} className="font-semibold hover:text-primary">
              {match.title}
            </Link>
            <span> · {duplicateReasonLabel(match.reason)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function isHackerNewsItem(item: PreviewItem): item is HackerNewsPreviewItem {
  return "hn_id" in item;
}

function itemKey(item: PreviewItem) {
  return isHackerNewsItem(item) ? `hn-${item.hn_id}` : `web-${item.source_id}`;
}

function skippedKey(item: { hn_id?: number; source_id?: string }) {
  return item.hn_id ? `HN ${item.hn_id}` : `URL ${item.source_id}`;
}

function duplicateReasonLabel(reason: DuplicateMatch["reason"]) {
  if (reason === "same_url") {
    return "같은 URL";
  }
  if (reason === "similar_title") {
    return "비슷한 제목";
  }
  return "RAG 유사";
}
