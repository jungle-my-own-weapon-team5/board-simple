"use client";

import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import { Card, CardContent } from "./ui/card";
import { Textarea } from "./ui/textarea";

type MarkdownEditorProps = {
  value: string;
  onChange: (value: string) => void;
};

export default function MarkdownEditor({ value, onChange }: MarkdownEditorProps) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <label className="flex min-w-0 flex-col gap-2 text-sm font-semibold">
        <span>Markdown</span>
        <Textarea
          value={value}
          onChange={(event) => onChange(event.target.value)}
          rows={14}
          placeholder="Markdown으로 내용을 작성하세요. #태그명 형식으로 태그를 추가할 수 있습니다."
        />
      </label>
      <Card className="min-w-0" aria-label="Markdown preview">
        <CardContent className="p-4">
          <span className="mb-2 block text-sm font-extrabold">Preview</span>
          <div className="markdown-body">
            <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>{value}</ReactMarkdown>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
