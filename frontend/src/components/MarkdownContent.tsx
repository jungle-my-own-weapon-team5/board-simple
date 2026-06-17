"use client";

import { Children, cloneElement, isValidElement, ReactNode, type ComponentPropsWithoutRef, type ReactElement } from "react";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import { cn } from "@/lib/utils";
import TagChip from "./TagChip";

type MarkdownContentProps = {
  value: string;
  className?: string;
  emptyText?: string;
};

type MarkdownPart =
  | { type: "markdown"; content: string }
  | { type: "font"; font: "sans" | "serif" | "mono"; content: string };

const FONT_BLOCK_PATTERN = /:::(sans|serif|mono)\n([\s\S]*?)\n:::/g;
const INLINE_TAG_PATTERN = /(^|\s)#([0-9A-Za-z가-힣_]{1,50})(?=$|\s|[.,!?;:)\]}])/g;

const markdownComponents = {
  p({ children, ...props }: ComponentPropsWithoutRef<"p">) {
    return <p {...props}>{renderInlineHashtags(children)}</p>;
  },
  li({ children, ...props }: ComponentPropsWithoutRef<"li">) {
    return <li {...props}>{renderInlineHashtags(children)}</li>;
  },
};

function fontClass(font: "sans" | "serif" | "mono") {
  if (font === "serif") {
    return "font-serif";
  }
  if (font === "mono") {
    return "font-mono";
  }
  return "font-sans";
}

function splitMarkdownContent(value: string): MarkdownPart[] {
  const parts: MarkdownPart[] = [];
  let lastIndex = 0;

  for (const match of value.matchAll(FONT_BLOCK_PATTERN)) {
    const index = match.index ?? 0;
    if (index > lastIndex) {
      parts.push({ type: "markdown", content: value.slice(lastIndex, index) });
    }
    parts.push({
      type: "font",
      font: match[1] as "sans" | "serif" | "mono",
      content: match[2],
    });
    lastIndex = index + match[0].length;
  }

  if (lastIndex < value.length) {
    parts.push({ type: "markdown", content: value.slice(lastIndex) });
  }

  return parts.length > 0 ? parts : [{ type: "markdown", content: value }];
}

function renderInlineHashtags(children: ReactNode, keyPrefix = "tag"): ReactNode {
  return Children.map(children, (child, index) => {
    if (typeof child === "string") {
      return renderTaggedText(child, `${keyPrefix}-${index}`);
    }
    if (isValidElement(child)) {
      const element = child as ReactElement<{ children?: ReactNode }>;
      if (element.props.children) {
        return cloneElement(element, {
          children: renderInlineHashtags(element.props.children, `${keyPrefix}-${index}`),
        });
      }
    }
    return child;
  });
}

function renderTaggedText(text: string, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;

  for (const match of text.matchAll(INLINE_TAG_PATTERN)) {
    const index = match.index ?? 0;
    const prefix = match[1];
    const tagName = match[2];
    const tagStartIndex = index + prefix.length;

    if (tagStartIndex > lastIndex) {
      nodes.push(text.slice(lastIndex, tagStartIndex));
    }
    nodes.push(<TagChip key={`${keyPrefix}-${tagStartIndex}-${tagName}`} name={tagName} compact />);
    lastIndex = tagStartIndex + tagName.length + 1;
  }

  if (lastIndex < text.length) {
    nodes.push(text.slice(lastIndex));
  }
  return nodes;
}

export default function MarkdownContent({ value, className, emptyText = "" }: MarkdownContentProps) {
  const source = value || emptyText;
  const parts = splitMarkdownContent(source);

  return (
    <div className={cn("markdown-body", className)}>
      {parts.map((part, index) => {
        if (part.type === "font") {
          return (
            <div key={`${part.type}-${index}`} className={fontClass(part.font)}>
              <ReactMarkdown rehypePlugins={[rehypeSanitize]} components={markdownComponents}>{part.content}</ReactMarkdown>
            </div>
          );
        }
        return <ReactMarkdown key={`${part.type}-${index}`} rehypePlugins={[rehypeSanitize]} components={markdownComponents}>{part.content}</ReactMarkdown>;
      })}
    </div>
  );
}
