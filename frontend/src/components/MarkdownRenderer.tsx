"use client";

import type { Html, PhrasingContent, Root } from "mdast";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { visit } from "unist-util-visit";
import { createHeadingIdGenerator, normalizeMarkdownHeadingText } from "@/lib/markdownHeadings";
import { cn } from "@/lib/utils";

type MarkdownRendererProps = {
  content: string;
  className?: string;
};

type SanitizeSchema = NonNullable<Parameters<typeof rehypeSanitize>[0]>;

const underlinePattern = /\+\+([^+\n]+?)\+\+/g;

const markdownSanitizeSchema: SanitizeSchema = {
  ...defaultSchema,
  clobberPrefix: "user-content-",
  tagNames: [...(defaultSchema.tagNames ?? []), "u"],
  attributes: {
    ...defaultSchema.attributes,
    h1: [...(defaultSchema.attributes?.h1 ?? []), "id"],
    h2: [...(defaultSchema.attributes?.h2 ?? []), "id"],
    h3: [...(defaultSchema.attributes?.h3 ?? []), "id"],
    code: [
      ...(defaultSchema.attributes?.code ?? []),
      ["className", /^language-/, "math-inline", "math-display"],
    ],
  },
};

function escapeHtml(value: string) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function splitUnderlineText(value: string): PhrasingContent[] {
  const nodes: PhrasingContent[] = [];
  let lastIndex = 0;

  for (const match of value.matchAll(underlinePattern)) {
    const index = match.index ?? 0;

    if (index > lastIndex) {
      nodes.push({ type: "text", value: value.slice(lastIndex, index) });
    }

    const underlineNode: Html = {
      type: "html",
      value: `<u>${escapeHtml(match[1])}</u>`,
    };
    nodes.push(underlineNode);
    lastIndex = index + match[0].length;
  }

  if (nodes.length === 0) {
    return [{ type: "text", value }];
  }

  if (lastIndex < value.length) {
    nodes.push({ type: "text", value: value.slice(lastIndex) });
  }

  return nodes;
}

function remarkUnderlineShortcut() {
  return (tree: Root) => {
    visit(tree, "text", (node, index, parent) => {
      if (!parent || index === undefined || !node.value.includes("++")) {
        return;
      }

      const replacement = splitUnderlineText(node.value);

      if (replacement.length === 1 && replacement[0].type === "text" && replacement[0].value === node.value) {
        return;
      }

      const children = parent.children as PhrasingContent[];
      children.splice(index, 1, ...replacement);
      return index + replacement.length;
    });
  };
}

type MarkdownTextNode = {
  alt?: string | null;
  children?: MarkdownTextNode[];
  type?: string;
  value?: string;
};

function getMarkdownNodeText(node: MarkdownTextNode): string {
  if (node.type === "image") {
    return node.alt ?? "";
  }

  if (typeof node.value === "string") {
    return node.value;
  }

  return node.children?.map(getMarkdownNodeText).join("") ?? "";
}

function remarkHeadingAnchors() {
  return (tree: Root) => {
    const createHeadingId = createHeadingIdGenerator();

    visit(tree, "heading", (node) => {
      if (node.depth > 3) {
        return;
      }

      const text = normalizeMarkdownHeadingText(getMarkdownNodeText(node));

      if (!text) {
        return;
      }

      node.data ??= {};
      node.data.hProperties = {
        ...(node.data.hProperties ?? {}),
        id: createHeadingId(text),
      };
    });
  };
}

export default function MarkdownRenderer({ content, className }: MarkdownRendererProps) {
  return (
    <div className={cn("markdown-body", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkMath, remarkUnderlineShortcut, remarkHeadingAnchors]}
        rehypePlugins={[
          rehypeRaw,
          [rehypeSanitize, markdownSanitizeSchema],
          rehypeKatex,
          [rehypeHighlight, { ignoreMissing: true }],
        ]}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
