"use client";

import { Send } from "lucide-react";
import Link from "next/link";
import { FormEvent, useState } from "react";
import * as ragApi from "../api/rag";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Textarea } from "../components/ui/textarea";
import type { RagAskResponse } from "../types";

export default function AskPage() {
  const [question, setQuestion] = useState("");
  const [data, setData] = useState<RagAskResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion) {
      setError("질문을 입력해 주세요.");
      return;
    }

    setIsLoading(true);
    setError(null);
    try {
      setData(await ragApi.askRag({ question: trimmedQuestion }));
    } catch (err) {
      setError(err instanceof Error ? err.message : "답변을 생성하지 못했습니다.");
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <section className="flex flex-col gap-5">
      <header>
        <h1 className="text-3xl font-extrabold leading-tight sm:text-4xl">뉴스 Q&A</h1>
      </header>

      <form className="flex flex-col gap-3" onSubmit={handleSubmit}>
        <Textarea
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="질문"
          className="min-h-36"
          maxLength={2000}
        />
        <div className="flex justify-end">
          <Button type="submit" disabled={isLoading}>
            <Send />
            <span>{isLoading ? "생성 중" : "질문하기"}</span>
          </Button>
        </div>
      </form>

      {error ? <p className="font-semibold text-destructive">{error}</p> : null}

      {data ? (
        <div className="flex flex-col gap-5">
          <section className="whitespace-pre-wrap border-y border-border py-5 leading-7">
            {data.answer}
          </section>

          <section className="flex flex-col gap-3">
            <h2 className="text-xl font-extrabold">출처</h2>
            {data.sources.length ? (
              data.sources.map((source, index) => (
                <Card key={`${source.post_id}-${index}`}>
                  <CardContent className="flex flex-col gap-2 p-4">
                    <div className="flex flex-col justify-between gap-1 md:flex-row md:items-start">
                      <Link
                        href={`/posts/${source.post_id}`}
                        className="font-extrabold [overflow-wrap:anywhere] hover:text-primary"
                      >
                        {source.title}
                      </Link>
                      {source.score === null ? null : (
                        <span className="text-xs text-muted-foreground">
                          score {source.score.toFixed(3)}
                        </span>
                      )}
                    </div>
                    <p className="text-sm leading-6 text-muted-foreground [overflow-wrap:anywhere]">
                      {source.excerpt}
                    </p>
                  </CardContent>
                </Card>
              ))
            ) : (
              <p className="text-muted-foreground">표시할 출처가 없습니다.</p>
            )}
          </section>
        </div>
      ) : null}
    </section>
  );
}
